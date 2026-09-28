package ocelot.spike;

import com.google.gson.*;
import com.mojang.authlib.GameProfile;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import li.cil.oc.api.internal.Robot;
import li.cil.oc.api.network.Connector;
import li.cil.oc.common.item.data.RobotData;
import net.minecraft.block.Block;
import net.minecraft.block.properties.IProperty;
import net.minecraft.block.state.IBlockState;
import net.minecraft.init.Blocks;
import net.minecraft.init.Items;
import net.minecraft.item.Item;
import net.minecraft.item.ItemStack;
import net.minecraft.nbt.JsonToNBT;
import net.minecraft.tileentity.TileEntity;
import net.minecraft.util.EnumFacing;
import net.minecraft.util.ResourceLocation;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.WorldServer;
import net.minecraftforge.common.util.FakePlayer;
import net.minecraftforge.common.util.FakePlayerFactory;

/** Real server-thread robot lifecycle for the selected runner scenario. */
final class RunnerRuntime {
    final RunnerScenario spec;
    private final WorldServer world;
    private final Path root;
    private RunnerProgram program;
    private RunnerObservations observations;
    private RunnerScheduler scheduler;
    private Robot robot;
    private Field stateField, completedWorkerField;
    private boolean booted;
    private boolean prebootObserved;
    private long diskReadNanos, workerWaitNanos, observationNanos;
    private String status="not_returned",message="";
    RunnerRuntime(RunnerScenario spec,WorldServer world,Path root) {
        this.spec=spec;this.world=world;this.root=root;
        if(spec.hardware!=null && !spec.mode.equals("baseline"))
            scheduler=RunnerScheduler.bind(spec.mode.equals("coordinated"),RunnerAsyncWork::nativeIdle);
    }
    boolean ready() {return robot!=null;}
    private static BlockPos pos(int[] p) {return RunnerObservations.pos(p);}
    void setup() throws Exception {
        checkOtherMachines();
        for(JsonElement entry:spec.blocks) {
            JsonObject volume=entry.getAsJsonObject(); int[] min=RunnerScenario.position(volume.get("min")),max=RunnerScenario.position(volume.get("max"));
            IBlockState state=blockState(volume);
            for(int x=min[0];x<=max[0];x++) for(int y=min[1];y<=max[1];y++) for(int z=min[2];z<=max[2];z++)
                world.setBlockState(new BlockPos(x,y,z),state,3);
        }
        BlockPos location=pos(spec.position);
        if(!world.isAirBlock(location)) throw new IllegalStateException("robot_cell_not_air");
        program=new RunnerProgram(root);
        byte[] bios;
        try(InputStream input=getClass().getClassLoader().getResourceAsStream("assets/opencomputers/lua/bios.lua")) {
            if(input==null) throw new IOException("Pinned OC BIOS absent");
            ByteArrayOutputStream output=new ByteArrayOutputStream();byte[] buffer=new byte[4096];int n;
            while((n=input.read(buffer))!=-1) {output.write(buffer,0,n);if(output.size()>4096) throw new IOException("OC BIOS EEPROM bound");}
            bios=output.toByteArray();
        }
        ItemStack firmware=li.cil.oc.api.Items.registerEEPROM("robot-runner-bios",bios,new byte[0],false);
        RunnerHardware hardware=spec.hardware==null?null:RunnerHardware.assemble(spec.hardware,firmware);
        RobotData data;
        if(hardware==null) {
            ItemStack floppy=program.provision(spec.entry,bios);
            data=new RobotData();data.tier_$eq(2);
            data.components_$eq(new ItemStack[]{RunnerHardware.oc("cpu3"),RunnerHardware.oc("ram6"),RunnerHardware.oc("inventoryupgrade"),firmware,floppy});
        } else {
            data=hardware.data;
            program.provision(spec.entry,bios,hardware.bootDrive);
        }
        data.name_$eq("runner-robot");
        data.robotEnergy_$eq((int)Math.ceil(spec.energy));data.totalEnergy_$eq((int)Math.ceil(spec.energy));
        ItemStack stack=data.createItemStack();Block block=Block.getBlockFromItem(stack.getItem());
        world.setBlockState(location,block.getDefaultState(),3);
        FakePlayer owner=FakePlayerFactory.get(world,new GameProfile(UUID.fromString("933cfa95-d269-48dd-8ed0-3c38ef1983fa"),"spike-owner"));
        owner.setPosition(location.getX()+0.5,location.getY(),location.getZ()+0.5);owner.rotationYaw=180;
        block.onBlockPlacedBy(world,location,world.getBlockState(location),owner,stack);
        Object proxy=world.getTileEntity(location);
        robot=(Robot)proxy.getClass().getMethod("robot").invoke(proxy);
        robot.getClass().getMethod("setFromFacing",EnumFacing.class).invoke(robot,EnumFacing.valueOf(spec.facing.toUpperCase(Locale.ROOT)));
        if(hardware!=null) hardware.equip(robot);
        robot.getClass().getMethod("connectComponents").invoke(robot);
        robot.setInventorySlotContents(0,item(spec.tool,1));
        for(JsonElement element:spec.inventory) {
            JsonObject input=element.getAsJsonObject();int slot=RunnerScenario.integer(input.get("slot"),1,spec.hardware==null?16:64);
            if(slot>robot.mainInventory().getSizeInventory()) throw new IllegalArgumentException("robot inventory capacity");
            robot.mainInventory().setInventorySlotContents(slot-1,item(input,RunnerScenario.integer(input.get("count"),1,64)));
        }
        // OC's native probabilistic damage rounding uses this agent's RNG. Seeding
        // is explicit; it does not replace damage rules or claim whole-world replay.
        if(spec.randomSeed!=null) robot.player().getRNG().setSeed(spec.randomSeed.longValue());
        if(scheduler!=null) scheduler.attach((Runnable)robot.machine());
        stateField=robot.machine().getClass().getDeclaredField("state");stateField.setAccessible(true);
        completedWorkerField=robot.machine().getClass().getDeclaredField("cpuTotal");completedWorkerField.setAccessible(true);
        // Component network/connector capacity are not ready on placement tick.
        // Initial observation is deferred until immediately before the real machine starts.
    }
    static ItemStack item(JsonObject obj,int count) throws Exception {
        String key=RunnerScenario.string(obj.get("item"));ResourceLocation id=new ResourceLocation(key);
        if(!Item.REGISTRY.containsKey(id) || Item.REGISTRY.getObject(id)==Items.AIR) throw new IllegalArgumentException("unknown item: "+key);
        ItemStack stack=new ItemStack(Item.REGISTRY.getObject(id),count,RunnerScenario.integer(obj.get("metadata"),0,32767));
        stack.setTagCompound(JsonToNBT.getTagFromJson(RunnerScenario.string(obj.get("nbt"))));
        if(count>stack.getMaxStackSize()) throw new IllegalArgumentException("illegal item stack: "+key);
        return stack;
    }
    @SuppressWarnings({"unchecked","rawtypes"}) private static IBlockState property(IBlockState state,String key,String value) {
        for(IProperty prop:state.getPropertyKeys()) if(prop.getName().equals(key)) {
            com.google.common.base.Optional<?> parsed=prop.parseValue(value);if(!parsed.isPresent()) break;
            return state.withProperty(prop,(Comparable)parsed.get());
        }
        throw new IllegalArgumentException("illegal block property: "+key+"="+value);
    }
    private static IBlockState blockState(JsonObject input) {
        String key=RunnerScenario.string(input.get("block"));ResourceLocation id=new ResourceLocation(key);
        if(!Block.REGISTRY.containsKey(id)) throw new IllegalArgumentException("unknown block: "+key);
        IBlockState state=Block.REGISTRY.getObject(id).getDefaultState();
        for(Map.Entry<String,JsonElement> entry:input.getAsJsonObject("properties").entrySet())
            state=property(state,entry.getKey(),RunnerScenario.string(entry.getValue()));
        return state;
    }
    String machineState() throws Exception {
        Object stack=stateField.get(robot.machine());synchronized(stack) {return String.valueOf(stack.getClass().getMethod("top").invoke(stack));}
    }
    /** Returns terminal reason, or null if work continues. */
    String tick(long tick,String mode) throws Exception {
        checkOtherMachines();
        if(!booted) {
            if(shouldPreparePreboot(tick,robot.node().network()!=null,prebootObserved)) {
                Connector power=(Connector)robot.machine().node();
                double before=power.globalBuffer(), capacity=power.globalBufferSize();
                double remainder=power.changeBuffer(spec.energy-before);
                if(Math.abs(power.globalBuffer()-spec.energy)>0.000001) {
                    Connector host=robot.node() instanceof Connector ? (Connector)robot.node() : null;
                    throw new IllegalStateException("preboot_energy_capacity tick="+tick+" requested="+spec.energy+
                        " machineGlobal="+power.globalBuffer()+" machineCapacity="+capacity+
                        " machineLocal="+power.localBuffer()+" machineLocalCapacity="+power.localBufferSize()+
                        " before="+before+" remainder="+remainder+
                        " hostConnector="+(host!=null)+" hostGlobal="+(host==null?-1:host.globalBuffer())+
                        " hostCapacity="+(host==null?-1:host.globalBufferSize())+
                        " hostLocal="+(host==null?-1:host.localBuffer())+
                        " hostLocalCapacity="+(host==null?-1:host.localBufferSize())+
                        " network="+(power.network()!=null));
                }
                if(spec.hardware!=null) program.observeNativeDrive(robot);
                observations=new RunnerObservations(spec,world,robot,root);
                observations.sample("initial",tick,machineState());
                prebootObserved=true;
                boolean floppy=false,eeprom=false;
                for(int slot=0;slot<robot.getSizeInventory();slot++) {
                    Object component=robot.getComponentInSlot(slot);
                    if(component instanceof li.cil.oc.server.component.EEPROM) eeprom=true;
                    if(component!=null && component.getClass().getName().contains("FileSystem")) floppy=true;
                }
                if(!eeprom || !floppy) throw new IllegalStateException("boot media components absent");
                if(!robot.machine().start()) throw new IllegalStateException("Robot would not start: "+robot.machine().lastError());
                booted=true;
            }
        } else {
            long observedAt=System.nanoTime();
            String outcome=program.outcome();
            diskReadNanos+=System.nanoTime()-observedAt;
            if(outcome.startsWith("returned\n")) status="returned";
            else if(outcome.startsWith("error\n")) {status="error";message=outcome.substring(6);}
            if(scheduler!=null || mode.equals("coordinated")) {
                long waitedAt=System.nanoTime();
                try {if(scheduler!=null) scheduler.checkProgress();else awaitWorker();}
                finally {workerWaitNanos+=System.nanoTime()-waitedAt;}
            }
            String state=machineState();
            if(state.equals("Stopped")) return status.equals("returned") ? (assertions()?"passed":"assertion_failed") : "program_not_returned";
            // A worker can enter Stopping after OC's START machine.update but before its
            // tile update unregisters the robot (isRunning is already false). In that
            // ordering no native close was queued by Machine.stop(). Queue OC's own
            // END closure until it reaches actual Stopped; do not force machine.update.
            if(needsNativeClose(state))
                li.cil.oc.common.EventHandler$.MODULE$.scheduleClose((li.cil.oc.server.machine.Machine)robot.machine());
            if(!robot.machine().isRunning() && robot.machine().lastError()!=null) return "robot_error:"+robot.machine().lastError();
        }
        if(prebootObserved && tick%spec.everyTicks==0) {
            long sampledAt=System.nanoTime();
            try {observations.sample("sample",tick,machineState());}
            finally {observationNanos+=System.nanoTime()-sampledAt;}
            if(observations.stalled(tick)) return "stall_limit";
        }
        return null;
    }
    static boolean shouldPreparePreboot(long tick,boolean networkReady,boolean alreadyObserved) {
        return tick>=3 && networkReady && !alreadyObserved;
    }
    private void checkOtherMachines() {
        // OC's Computer trait has optional mod interfaces absent on this compile classpath.
        for(net.minecraft.world.WorldServer dimension:world.getMinecraftServer().worlds) {
            for(TileEntity tile:new ArrayList<>(dimension.loadedTileEntityList))
                if(isMachineTile(tile.getClass()) && !isEmptyCreativePowerSource(tile) &&
                    (robot==null || dimension!=world || !tile.getPos().equals(((TileEntity)robot).getPos())))
                    throw new IllegalStateException("additional_loaded_oc_machine:"+tile.getPos());
            for(net.minecraft.entity.Entity entity:new ArrayList<>(dimension.loadedEntityList))
                if(isMachineEntity(entity.getClass()))
                    throw new IllegalStateException("additional_loaded_oc_machine:drone:"+entity.getPosition());
        }
    }
    private boolean isEmptyCreativePowerSource(TileEntity tile) {
        // An empty creative case is OC's native infinite energy source, not a
        // second programmable machine. Check every tick: adding any component
        // revokes this exception. Keep legacy scenarios' host restrictions.
        if(spec.hardware==null || !tile.getClass().getName().equals("li.cil.oc.common.tileentity.Case")) return false;
        try {
            boolean creative=Boolean.TRUE.equals(tile.getClass().getMethod("isCreative").invoke(tile));
            li.cil.oc.server.machine.Machine machine=(li.cil.oc.server.machine.Machine)tile.getClass().getMethod("machine").invoke(tile);
            return machine!=null && !machine.isExecuting() && emptyPowerSource(creative,machine.isRunning(),
                (net.minecraft.inventory.IInventory)tile);
        } catch(ReflectiveOperationException | ClassCastException e) {
            throw new IllegalStateException("creative_power_source_inspection",e);
        }
    }
    static boolean emptyPowerSource(boolean creative,boolean running,net.minecraft.inventory.IInventory inventory) {
        if(!creative || running) return false;
        for(int slot=0;slot<inventory.getSizeInventory();slot++) if(!inventory.getStackInSlot(slot).isEmpty()) return false;
        return true;
    }
    static boolean isMachineTile(Class<?> type) {
        return hasNamedAncestor(type,false) || hasComputerTrait(type);
    }
    static boolean isMachineEntity(Class<?> type) {
        return hasNamedAncestor(type,true);
    }
    private static boolean hasNamedAncestor(Class<?> type,boolean entity) {
        return type!=null && (isMachineHostName(type.getName(),entity) || hasNamedAncestor(type.getSuperclass(),entity));
    }
    static boolean isMachineHostName(String typeName,boolean entity) {
        return typeName.equals(entity?"li.cil.oc.common.entity.Drone":"li.cil.oc.common.tileentity.Rack");
    }
    private static boolean hasComputerTrait(Class<?> type) {
        if(type==null) return false;
        for(Class<?> iface:type.getInterfaces())
            if(iface.getName().equals("li.cil.oc.common.tileentity.traits.Computer") || hasComputerTrait(iface)) return true;
        return hasComputerTrait(type.getSuperclass());
    }
    static boolean needsNativeClose(String state) {return state.equals("Stopping");}
    static boolean runnerWorkerNeedsTime(String state,boolean executing,boolean workerCompletedThisTick) {
        // OC can immediately requeue Yielded on pending signals (Machine.scala:1004-1011).
        // One completed worker pass per END rendezvous bounds world advancement
        // without spinning forever on repeated requeues or skipping an unrun task.
        return !(workerCompletedThisTick && !executing && state.equals("Yielded"))
                && RobotSpike.workerNeedsTime(state,executing);
    }
    private long completedWorkerNanos() throws Exception {
        return completedWorkerField.getLong(robot.machine());
    }
    private void awaitWorker() throws Exception {
        long deadline=System.nanoTime()+1000000000L;
        long before=completedWorkerNanos();
        while(true) {
            String state=machineState();
            boolean completed=completedWorkerNanos()>before;
            if(!runnerWorkerNeedsTime(state,((li.cil.oc.server.machine.Machine)robot.machine()).isExecuting(),completed)) return;
            if(System.nanoTime()>=deadline || Thread.currentThread().isInterrupted())
                throw new IllegalStateException("worker_progress_limit:"+state+" "+workerDiagnostic(robot.machine()));
            java.util.concurrent.locks.LockSupport.parkNanos(10000L);
        }
    }
    private static String workerDiagnostic(li.cil.oc.api.machine.Machine machine) {
        StringBuilder text=new StringBuilder("computer_workers=");
        for(Map.Entry<Thread,StackTraceElement[]> entry:Thread.getAllStackTraces().entrySet()) {
            Thread thread=entry.getKey();
            if(!thread.getName().contains("Computer")) continue;
            text.append('[').append(thread.getName()).append(':').append(thread.getState());
            StackTraceElement[] frames=entry.getValue();
            for(int i=0;i<Math.min(6,frames.length);i++) text.append('|').append(frames[i].getClassName()).append('.').append(frames[i].getMethodName());
            text.append(']');
            if(text.length()>3000) break;
        }
        try {
            Field stack=machine.getClass().getDeclaredField("state"); stack.setAccessible(true);
            Object value=stack.get(machine); synchronized(value) {text.append(" stack=").append(value);}
            for(String key:new String[]{"remainingPause","remainIdle"}) {
                Field field=machine.getClass().getDeclaredField(key);field.setAccessible(true);
                text.append(' ').append(key).append('=').append(field.get(machine));
            }
            Class<?> companion=Class.forName("li.cil.oc.server.machine.Machine$");
            Field module=companion.getField("MODULE$");
            Object owner=module.get(null);
            for(Field field:companion.getDeclaredFields()) if(field.getName().contains("threadPool")) {
                field.setAccessible(true);Object pool=field.get(owner);
                if(pool instanceof java.util.concurrent.ScheduledThreadPoolExecutor) {
                    java.util.concurrent.ScheduledThreadPoolExecutor executor=(java.util.concurrent.ScheduledThreadPoolExecutor)pool;
                    text.append(" queueSize=").append(executor.getQueue().size());
                    Runnable next=executor.getQueue().peek();
                    if(next instanceof java.util.concurrent.Delayed) text.append(" nextDelayMillis=")
                        .append(((java.util.concurrent.Delayed)next).getDelay(java.util.concurrent.TimeUnit.MILLISECONDS));
                }
            }
        } catch(Exception error) {text.append(" diagnosticError=").append(error.getClass().getSimpleName());}
        return text.substring(0,Math.min(4500,text.length()));
    }
    private boolean assertions() {
        if(spec.expect.has("position") && !((TileEntity)robot).getPos().equals(pos(RunnerScenario.position(spec.expect.get("position"))))) return false;
        for(JsonElement e:spec.expectedBlocks) {
            JsonObject b=e.getAsJsonObject();BlockPos location=pos(RunnerScenario.position(b.get("position")));
            if(!String.valueOf(world.getBlockState(location).getBlock().getRegistryName()).equals(RunnerScenario.string(b.get("block")))) return false;
        }
        for(JsonElement e:spec.expectedInventory) {
            JsonObject wanted=e.getAsJsonObject();int total=0;
            for(int slot=0;slot<robot.mainInventory().getSizeInventory();slot++) {
                ItemStack stack=robot.mainInventory().getStackInSlot(slot);
                if(!stack.isEmpty() && String.valueOf(stack.getItem().getRegistryName()).equals(RunnerScenario.string(wanted.get("item")))) total+=stack.getCount();
            }
            if(total<RunnerScenario.integer(wanted.get("minCount"),0,1024)) return false;
        }
        return true;
    }
    JsonObject result(long tick) {
        if(scheduler!=null) scheduler.close();
        JsonObject value=new JsonObject();value.addProperty("runnerSchemaVersion",1);value.addProperty("scenarioId",spec.id);
        value.add("robot",JsonNull.INSTANCE); // setup failures may have no robot state to report.
        JsonObject timing=new JsonObject();timing.addProperty("diskReadNanos",diskReadNanos);
        timing.addProperty("workerWaitNanos",workerWaitNanos);
        if(scheduler!=null) {
            timing.addProperty("workerScheduling","idle-compression");
            timing.addProperty("workerPasses",scheduler.workerPasses());
            timing.addProperty("skippedIdleNanos",scheduler.skippedNanos());
        }
        timing.addProperty("observationNanos",observationNanos);value.add("runnerTiming",timing);
        JsonObject programResult=new JsonObject();programResult.addProperty("status",status);
        programResult.addProperty("message",message.length()>8192?message.substring(0,8192):message);value.add("program",programResult);
        try {if(program!=null && program.observing()) program.exportConsole();}
        catch(Exception e) {artifactError(value,e);}
        try {
            if(observations!=null) {observations.sample("final",tick,machineState());value.add("robot",observations.robot(machineState()));}
        } catch(Exception e) {artifactError(value,e);}
        try {if(observations!=null) {observations.close();value.add("observationCoverage",observations.coverage());}}
        catch(Exception e) {artifactError(value,e);}
        try {if(program!=null) program.close();}
        catch(Exception e) {artifactError(value,e);}
        return value;
    }
    private static void artifactError(JsonObject result,Exception error) {
        String earlier=result.has("runnerArtifactError")?result.get("runnerArtifactError").getAsString()+";":"";
        String detail=earlier+error.getClass().getSimpleName()+":"+error.getMessage();
        result.addProperty("runnerArtifactError",detail.substring(0,Math.min(8192,detail.length())));
    }
}
