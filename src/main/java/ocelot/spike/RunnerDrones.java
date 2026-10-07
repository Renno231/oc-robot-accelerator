package ocelot.spike;

import com.google.gson.*;
import com.mojang.authlib.GameProfile;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import li.cil.oc.common.entity.Drone;
import li.cil.oc.common.template.AssemblerTemplates;
import li.cil.oc.common.template.AssemblerTemplates$;
import li.cil.oc.api.network.Connector;
import net.minecraft.inventory.InventoryBasic;
import net.minecraft.item.ItemStack;
import net.minecraft.util.math.Vec3d;
import net.minecraft.world.WorldServer;
import net.minecraftforge.common.util.FakePlayer;
import net.minecraftforge.common.util.FakePlayerFactory;

/** Native drone assembly, placement, start, lifecycle and recording. */
final class RunnerDrones {
    private final RunnerScenario spec;
    private final WorldServer world;
    private final Path root;
    private final List<Drone> drones=new ArrayList<>();
    private final List<Vec3d> spawned=new ArrayList<>();
    private final List<RunnerDroneErrors> errors=new ArrayList<>();
    private RunnerRecording recording;
    private RunnerRouteMetrics routeMetrics;
    private long sequence;
    private boolean started,storageRoomChestPlaced;
    private RunnerComputer computer,secondComputer;
    private final Map<net.minecraft.util.math.BlockPos,net.minecraft.block.state.IBlockState> previous=new HashMap<>();
    private final RunnerObservations.StallClock stall=new RunnerObservations.StallClock();
    RunnerDrones(RunnerScenario spec,WorldServer world,Path root) {this.spec=spec;this.world=world;this.root=root;}
    boolean owns(net.minecraft.entity.Entity entity) {return drones.contains(entity);}
    static void validateReload(JsonObject identity,String scenario,int count) {
        if(!identity.get("scenario").getAsString().equals(scenario)) throw new IllegalStateException("reload_scenario_identity");
        JsonArray saved=identity.getAsJsonArray("drones");
        if(saved.size()!=count) throw new IllegalStateException("reload_drone_count");
        Set<String> uuids=new HashSet<>(),addresses=new HashSet<>();
        for(JsonElement e:saved) {
            JsonObject d=e.getAsJsonObject();String uuid=UUID.fromString(d.get("uuid").getAsString()).toString();
            String address=UUID.fromString(d.get("address").getAsString()).toString();
            if(!uuids.add(uuid) || !addresses.add(address)) throw new IllegalStateException("reload_duplicate_drone");
        }
    }
    void restore(JsonObject identity) throws Exception {
        validateReload(identity,spec.id,spec.v4.drones.size());
        JsonArray saved=identity.getAsJsonArray("drones");
        for(JsonElement e:saved) {
            JsonObject d=e.getAsJsonObject();net.minecraft.entity.Entity entity=world.getEntityFromUuid(UUID.fromString(d.get("uuid").getAsString()));
            if(!(entity instanceof Drone)) throw new IllegalStateException("reload_drone_absent");
            Drone drone=(Drone)entity;
            if(!drone.machine().node().address().equals(d.get("address").getAsString())) throw new IllegalStateException("reload_drone_identity");
            RunnerScheduler.attachMachine((Runnable)drone.machine());drones.add(drone);
            spawned.add(new Vec3d(drone.posX,drone.posY,drone.posZ));errors.add(new RunnerDroneErrors(drone));
            if(!drone.machine().isRunning() && !drone.start()) throw new IllegalStateException("reload_drone_start_failed");
        }
        if(spec.v4.computer!=null) {computer=new RunnerComputer(spec.v4.computer,world,root);computer.restore(identity.getAsJsonObject("computer"));}
        if(spec.v4.secondComputer!=null) {secondComputer=new RunnerComputer(spec.v4.secondComputer,world,root);secondComputer.restore(identity.getAsJsonObject("secondComputer"));}
        recording=new RunnerRecording(root,spec.maxBytes,spec.onFull);started=true;sample("initial",0);
    }
    boolean captureReload() throws Exception {
        if(computer==null) throw new IllegalStateException("reload_probe_requires_controller");
        boolean cargo=false;
        for(Drone d:drones) if(d.posX>3.6 && d.posX<5.6 && RunnerContainers.contents(d.mainInventory()).size()>0) cargo=true;
        if(!cargo) return false;
        JsonObject data=new JsonObject();data.addProperty("scenario",spec.id);JsonArray ids=new JsonArray();
        for(Drone d:drones) {JsonObject id=new JsonObject();id.addProperty("uuid",d.getUniqueID().toString());id.addProperty("address",d.machine().node().address());ids.add(id);}
        data.add("drones",ids);data.add("snapshot",states());data.add("computer",computer.reloadIdentity());
        if(secondComputer!=null) data.add("secondComputer",secondComputer.reloadIdentity());
        computer.pendingReloadSignal();
        Files.write(root.resolve("reload-state.json"),data.toString().getBytes(StandardCharsets.UTF_8),StandardOpenOption.CREATE_NEW);
        world.getMinecraftServer().saveAllWorlds(false);return true;
    }
    boolean owns(net.minecraft.tileentity.TileEntity tile) {return (computer!=null && computer.owns(tile)) || (secondComputer!=null && secondComputer.owns(tile));}
    private static net.minecraft.util.math.BlockPos blockPosition(Drone drone) {
        return new net.minecraft.util.math.BlockPos(drone.posX,drone.posY,drone.posZ);
    }
    private static ItemStack assemble(JsonObject h,ItemStack firmware) {
        InventoryBasic inventory=new InventoryBasic("runner drone assembly",false,22);
        ItemStack casing=RunnerHardware.oc("dronecase"+h.get("tier").getAsString());inventory.setInventorySlotContents(0,casing);
        scala.Option<AssemblerTemplates.Template> selected=AssemblerTemplates$.MODULE$.select(casing);
        if(selected.isEmpty()) throw new IllegalStateException("native drone assembler template absent");
        AssemblerTemplates.Template template=selected.get();
        List<ItemStack> upgrades=new ArrayList<>(),components=new ArrayList<>();
        for(JsonElement e:h.getAsJsonArray("upgrades")) upgrades.add(RunnerHardware.oc(e.getAsString()));
        components.add(RunnerHardware.oc(h.get("cpu").getAsString()));
        for(String key:new String[]{"memory","cards"}) for(JsonElement e:h.getAsJsonArray(key)) components.add(RunnerHardware.oc(e.getAsString()));
        components.add(firmware);
        String tier=h.get("tier").getAsString();
        place(inventory,template.upgradeSlots(),4,upgrades,"upgrades",tier);
        place(inventory,template.componentSlots(),13,components,"components",tier);
        scala.Tuple3<Object,net.minecraft.util.text.ITextComponent,net.minecraft.util.text.ITextComponent[]> check=template.validate(inventory);
        if(!Boolean.TRUE.equals(check._1())) throw new IllegalArgumentException("invalid native drone assembly: "+
            (check._2()==null?"CPU, memory or complexity":check._2().getUnformattedText()));
        ItemStack result=template.assemble(inventory)._1();
        if(result.isEmpty()) throw new IllegalStateException("native drone assembler returned no drone");
        return result;
    }
    private static void place(InventoryBasic inventory,AssemblerTemplates.Slot[] slots,int offset,List<ItemStack> items,String label,String tier) {
        boolean[][] fits=new boolean[items.size()][slots.length];
        for(int i=0;i<items.size();i++) for(int s=0;s<slots.length;s++) fits[i][s]=slots[s].validate(inventory,offset+s,items.get(i));
        int[] assignment=RunnerHardware.match(fits,slots.length);
        if(assignment==null) {
            List<String> names=new ArrayList<>();
            for(ItemStack item:items) names.add(li.cil.oc.api.Items.get(item).name());
            throw new IllegalArgumentException("invalid native drone assembly: tier "+tier+" "+label+" do not fit native assembler slots/tier: "+names);
        }
        for(int i=0;i<items.size();i++) inventory.setInventorySlotContents(offset+assignment[i],items.get(i));
    }
    void setup() throws Exception {
        FakePlayer owner=FakePlayerFactory.get(world,new GameProfile(UUID.fromString("933cfa95-d269-48dd-8ed0-3c38ef1983fa"),"spike-owner"));
        for(JsonElement e:spec.v4.drones) {
            JsonObject d=e.getAsJsonObject();int[] p=RunnerScenario.position(d.get("position"));
            if(!world.isAirBlock(RunnerObservations.pos(p))) throw new IllegalArgumentException("drone_cell_not_air:"+Arrays.toString(p));
            Path file=root.resolve("eeprom").resolve(RunnerScenario.path(d.get("eeprom").getAsString()));
            int size=li.cil.oc.Settings$.MODULE$.get().eepromSize();
            if(Files.size(file)>size) throw new IllegalArgumentException("drone EEPROM exceeds configured code size: "+size);
            byte[] code=Files.readAllBytes(file),data=d.get("eepromData").getAsString().getBytes(StandardCharsets.UTF_8);
            if(data.length>li.cil.oc.Settings$.MODULE$.get().eepromDataSize()) throw new IllegalArgumentException("drone EEPROM data exceeds configured data size");
            ItemStack firmware=li.cil.oc.api.Items.registerEEPROM("runner-drone",code,data,false);
            ItemStack stack=assemble(d.getAsJsonObject("hardware"),firmware);
            Drone drone=new Drone(world);drone.ownerName_$eq(owner.getName());drone.ownerUUID_$eq(owner.getGameProfile().getId());
            RunnerScheduler.attachMachine((Runnable)drone.machine());
            // Same placement path as OC item/Drone.scala:50-63. Y is the declared
            // block's base, avoiding changing OC's round(Y)+0.5 power-up target.
            drone.initializeAfterPlacement(stack,owner,new Vec3d(p[0]+0.5,p[1],p[2]+0.5));
            if(!world.spawnEntity(drone)) throw new IllegalStateException("native drone spawn rejected");
            drones.add(drone);spawned.add(new Vec3d(drone.posX,drone.posY,drone.posZ));
            RunnerEnergyMetrics.track(drone.machine());
            errors.add(new RunnerDroneErrors(drone));
            RunnerContainers.fill(drone.mainInventory(),d.getAsJsonArray("inventory"),"drone "+(drones.size()-1));
        }
        if(spec.v4.computer!=null) {computer=new RunnerComputer(spec.v4.computer,world,root);computer.setup();}
        if(spec.v4.secondComputer!=null) {secondComputer=new RunnerComputer(spec.v4.secondComputer,world,root);secondComputer.setup();}
        if(Files.isRegularFile(root.resolve("program/route-metrics-enabled"))) routeMetrics=new RunnerRouteMetrics(root);
    }
    static String state(Drone drone) throws Exception {
        Field field=drone.machine().getClass().getDeclaredField("state");field.setAccessible(true);
        Object stack=field.get(drone.machine());synchronized(stack) {return String.valueOf(stack.getClass().getMethod("top").invoke(stack));}
    }
    String tick(long tick) throws Exception {
        if(routeMetrics!=null) routeMetrics.sample(tick,drones);
        // Native acceptance player action, scoped to the storage-room fixture.
        // Lua writes the marker only after mapping and earlier transfers finish.
        // It changes the real world, never a movement or success predicate.
        if(!storageRoomChestPlaced && "logistics-storage-room".equals(spec.id) && computer!=null && computer.storageRoomChestRequested()) {
            net.minecraft.util.math.BlockPos p=new net.minecraft.util.math.BlockPos(3,67,2);
            if(world.isAirBlock(p)) world.setBlockState(p,net.minecraft.init.Blocks.CHEST.getDefaultState(),3);
            computer.storageRoomChestPlaced();
            storageRoomChestPlaced=true;
        }
        if(!started) {
            if(tick<3) return null;
            if(computer!=null && !computer.prepare(tick)) return null;
            if(secondComputer!=null && !secondComputer.prepare(tick)) return null;
            for(int i=0;i<drones.size();i++) {
                Drone drone=drones.get(i);JsonObject d=spec.v4.drones.get(i).getAsJsonObject();
                Connector power=(Connector)drone.machine().node();
                if(d.has("energy")) {
                    double energy=d.get("energy").getAsDouble();
                    if(energy>power.globalBufferSize()) throw new IllegalArgumentException("drone "+i+" energy exceeds native capacity: "+power.globalBufferSize());
                    power.changeBuffer(energy-power.globalBuffer());
                }
            }
            recording=new RunnerRecording(root,spec.maxBytes,spec.onFull);sample("initial",tick);
            for(int i=0;i<drones.size();i++) if(!drones.get(i).start())
                throw new IllegalStateException("drone "+i+" would not start: "+drones.get(i).machine().lastError());
            started=true;
        } else {
            boolean stopped=true;
            for(int i=0;i<drones.size();i++) {
                Drone drone=drones.get(i);String state=state(drone);
                if(drone.isDead) return "drone_error:"+i+":entity removed";
                String error=errors.get(i).observe();if(error!=null) return "drone_error:"+i+":"+error;
                if(!state.equals("Stopped")) stopped=false;
                if(RunnerRuntime.needsNativeClose(state)) li.cil.oc.common.EventHandler$.MODULE$.scheduleClose((li.cil.oc.server.machine.Machine)drone.machine());
            }
            if(computer!=null) {
                String outcome=computer.tick();
                String other=secondComputer==null?"returned":secondComputer.tick();
                if(outcome!=null && !outcome.equals("returned")) return outcome;
                if(other!=null && !other.equals("returned")) return "second_"+other;
                if("returned".equals(outcome) && "returned".equals(other)) {
                    String failure=assertions();return failure==null?"passed":failure;
                }
            } else if(stopped) {String failure=assertions();return failure==null?"passed":failure;}
        }
        if(tick%spec.everyTicks==0) {sample("sample",tick);if(spec.stallTicks>0 && tick-stall.lastChangeTick()>=spec.stallTicks) return "stall_limit";}
        return null;
    }
    private String assertions() {
        String failure=RunnerContainers.assertions(spec,world);if(failure!=null) return failure;
        for(JsonElement e:spec.expectedBlocks) {
            JsonObject b=e.getAsJsonObject();net.minecraft.util.math.BlockPos p=RunnerContainers.pos(b);
            if(!String.valueOf(world.getBlockState(p).getBlock().getRegistryName()).equals(b.get("block").getAsString())) return "expectation_failed:block "+p;
        }
        for(JsonElement e:spec.v4.expectedDrones) {
            JsonObject d=e.getAsJsonObject();int index=d.get("index").getAsInt();Drone drone=drones.get(index);
            if(d.has("blockPosition") && !blockPosition(drone).equals(RunnerObservations.pos(RunnerScenario.position(d.get("blockPosition"))))) return "expectation_failed:drone "+index+" blockPosition expected "+d.get("blockPosition")+" actual "+blockPosition(drone);
            if(d.has("inventory")) {failure=RunnerContainers.checkSlots(drone.mainInventory(),d.getAsJsonArray("inventory"),"drone "+index+" inventory");if(failure!=null) return failure;}
            if(d.has("minEnergy") && ((Connector)drone.machine().node()).globalBuffer()<d.get("minEnergy").getAsDouble()) return "expectation_failed:drone "+index+" minEnergy "+d.get("minEnergy");
            if(d.has("running") && drone.machine().isRunning()!=d.get("running").getAsBoolean()) return "expectation_failed:drone "+index+" running "+d.get("running");
        }
        return null;
    }
    private static JsonArray exact(Vec3d p) {JsonArray a=new JsonArray();a.add(p.x);a.add(p.y);a.add(p.z);return a;}
    private JsonArray states() throws Exception {
        JsonArray result=new JsonArray();
        for(int i=0;i<drones.size();i++) {
            Drone drone=drones.get(i);JsonObject value=new JsonObject();value.addProperty("index",i);
            value.add("position",exact(new Vec3d(drone.posX,drone.posY,drone.posZ)));value.add("blockPosition",RunnerObservations.coords(blockPosition(drone)));
            value.add("declaredPosition",spec.v4.drones.get(i).getAsJsonObject().get("position"));value.add("spawnPosition",exact(spawned.get(i)));
            Connector power=(Connector)drone.machine().node();value.addProperty("energy",power.globalBuffer());value.addProperty("energyCapacity",power.globalBufferSize());
            value.addProperty("energyConsumed",RunnerEnergyMetrics.consumed(drone.machine()));
            value.addProperty("uptime",drone.machine().upTime());
            value.addProperty("state",state(drone));value.addProperty("lastError",drone.machine().lastError());
            value.addProperty("observedError",errors.get(i).observe());
            value.addProperty("running",drone.machine().isRunning());
            value.add("inventory",RunnerContainers.contents(drone.mainInventory()));result.add(value);
            value.addProperty("inventoryCapacity",drone.mainInventory().getSizeInventory());
        }
        return result;
    }
    private void sample(String kind,long tick) throws Exception {
        JsonObject value=new JsonObject();value.addProperty("schemaVersion",1);value.addProperty("sequence",sequence);value.addProperty("tick",tick);value.addProperty("kind",kind);
        value.addProperty("wallNanos",System.nanoTime());
        if(kind.equals("initial")) {JsonObject region=new JsonObject();region.add("min",RunnerObservations.coords(RunnerObservations.pos(spec.min)));region.add("max",RunnerObservations.coords(RunnerObservations.pos(spec.max)));value.add("region",region);value.addProperty("everyTicks",spec.everyTicks);}
        JsonArray changes=new JsonArray();
        for(int x=spec.min[0];x<=spec.max[0];x++) for(int y=spec.min[1];y<=spec.max[1];y++) for(int z=spec.min[2];z<=spec.max[2];z++) {
            net.minecraft.util.math.BlockPos p=new net.minecraft.util.math.BlockPos(x,y,z);JsonObject changed=RunnerObservations.changedBlock(previous,p,world.getBlockState(p));if(changed!=null) changes.add(changed);
        }
        value.add("blocks",changes);JsonArray state=states();value.add("drones",state);
        value.add("containers",RunnerContainers.result(spec,world));
        if(computer!=null) value.add("computer",computer.snapshot());
        if(secondComputer!=null) value.add("secondComputer",secondComputer.snapshot());
        if(recording.record(value.toString(),kind,tick)) sequence++;
        stall.observe(tick,state.toString()+(computer==null?"":"|"+value.get("computer"))+(secondComputer==null?"":"|"+value.get("secondComputer")),changes.size()>0);
    }
    JsonObject result(long tick) {
        JsonObject result=new JsonObject();result.addProperty("runnerSchemaVersion",1);result.addProperty("scenarioId",spec.id);
        try {if(recording!=null) sample("final",tick);result.add("drones",states());result.add("containers",RunnerContainers.result(spec,world));}
        catch(Exception ex) {result.addProperty("runnerArtifactError",ex.toString());}
        try {if(recording!=null) {recording.close();result.add("observationCoverage",recording.coverage());}}
        catch(Exception ex) {result.addProperty("runnerArtifactError",ex.toString());}
        if(computer!=null) {
            try {result.add("computer",computer.snapshot());result.add("program",computer.programResult());computer.close();}
            catch(Exception ex) {result.addProperty("runnerArtifactError",ex.toString());}
        }
        if(secondComputer!=null) {
            try {result.add("secondComputer",secondComputer.snapshot());secondComputer.close();}
            catch(Exception ex) {result.addProperty("runnerArtifactError",ex.toString());}
        }
        for(RunnerDroneErrors observer:errors) observer.close();
        if(routeMetrics!=null) try {routeMetrics.sample(tick,drones);routeMetrics.close();}
        catch(Exception ex) {result.addProperty("runnerArtifactError",ex.toString());}
        return result;
    }
}
