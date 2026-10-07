package ocelot.spike;

import com.google.gson.*;
import com.mojang.authlib.GameProfile;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.file.*;
import java.util.*;
import li.cil.oc.api.machine.Machine;
import li.cil.oc.api.network.Connector;
import net.minecraft.block.Block;
import net.minecraft.inventory.IInventory;
import net.minecraft.item.ItemStack;
import net.minecraft.tileentity.TileEntity;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.WorldServer;
import net.minecraftforge.common.util.FakePlayer;
import net.minecraftforge.common.util.FakePlayerFactory;

/** Native finite-powered case slots and the existing OpenOS wrapper/outcome mechanism. */
final class RunnerComputer {
    boolean storageRoomChestRequested() {return program.storageRoomChestRequested();}
    void storageRoomChestPlaced() {machine.signal("storage_room_chest_placed");}
    boolean warehouseRemovalRequested() {return program.warehouseRemovalRequested();}
    void warehouseItemsRemoved() {machine.signal("warehouse_items_removed");}
    private final JsonObject spec;
    private final WorldServer world;
    private final RunnerProgram program;
    private TileEntity tile;
    private Machine machine;
    private boolean started;
    private String status="not_returned",message="";
    RunnerComputer(JsonObject spec,WorldServer world,Path root) {this.spec=spec;this.world=world;program=new RunnerProgram(root,spec.getAsJsonObject("program").get("directory").getAsString());}
    boolean owns(TileEntity other) {return tile==other;}
    JsonObject reloadIdentity() {
        JsonObject data=new JsonObject();data.addProperty("address",machine.node().address());
        data.addProperty("disk",program.diskIdentity());data.add("position",spec.get("position"));return data;
    }
    void restore(JsonObject identity) throws Exception {
        if(!identity.get("position").equals(spec.get("position"))) throw new IllegalStateException("reload_case_position");
        tile=world.getTileEntity(RunnerContainers.pos(spec));
        if(tile==null || !tile.getClass().getName().equals("li.cil.oc.common.tileentity.Case")) throw new IllegalStateException("reload_case_absent");
        tile.getClass().getMethod("connectComponents").invoke(tile);
        machine=(Machine)tile.getClass().getMethod("machine").invoke(tile);
        if(!machine.node().address().equals(identity.get("address").getAsString())) throw new IllegalStateException("reload_case_identity");
        RunnerScheduler.attachMachine((Runnable)machine);program.restoreDiskIdentity(identity.get("disk").getAsString());
        scala.Option<?>[] components=(scala.Option<?>[])tile.getClass().getMethod("components").invoke(tile);
        program.observeNativeDrive((IInventory)tile,slot -> slot<components.length && components[slot].isDefined()?components[slot].get():null);
        if(!machine.isRunning() && !machine.start()) throw new IllegalStateException("reload_case_start_failed");
        started=true;
    }
    void pendingReloadSignal() {machine.pause(0.1);if(!machine.signal("runner_reload_pending","persisted")) throw new IllegalStateException("reload_signal_rejected");}
    void setup() throws Exception {
        BlockPos p=RunnerContainers.pos(spec);if(!world.isAirBlock(p)) throw new IllegalArgumentException("computer_cell_not_air:"+p);
        JsonObject h=spec.getAsJsonObject("hardware");ItemStack casing=RunnerHardware.oc("case"+h.get("tier").getAsString());
        Block block=Block.getBlockFromItem(casing.getItem());world.setBlockState(p,block.getDefaultState(),3);
        FakePlayer owner=FakePlayerFactory.get(world,new GameProfile(UUID.fromString("933cfa95-d269-48dd-8ed0-3c38ef1983fa"),"spike-owner"));
        owner.setPosition(p.getX()+0.5,p.getY(),p.getZ()+0.5);owner.rotationYaw=180;
        block.onBlockPlacedBy(world,p,world.getBlockState(p),owner,casing);
        tile=world.getTileEntity(p);if(tile==null || !tile.getClass().getName().equals("li.cil.oc.common.tileentity.Case")) throw new IllegalStateException("native case absent");
        IInventory inventory=(IInventory)tile;inventory.clear();
        List<ItemStack> parts=new ArrayList<>(),storage=new ArrayList<>();parts.add(part(h.get("cpu").getAsString(),"cpu"));
        for(String key:new String[]{"memory","cards"}) for(JsonElement e:h.getAsJsonArray(key)) parts.add(part(e.getAsString(),key.equals("cards")?"card":"memory"));
        for(JsonElement e:h.getAsJsonArray("storage")) storage.add(part(e.getAsString(),"hdd"));parts.addAll(storage);
        byte[] bios;
        try(InputStream in=getClass().getClassLoader().getResourceAsStream("assets/opencomputers/lua/bios.lua")) {
            if(in==null) throw new IOException("Pinned OC BIOS absent");ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[4096];int n;
            while((n=in.read(buffer))!=-1) {out.write(buffer,0,n);if(out.size()>li.cil.oc.Settings.get().eepromSize()) throw new IOException("OC BIOS EEPROM bound");}bios=out.toByteArray();
        }
        parts.add(li.cil.oc.api.Items.registerEEPROM("runner-computer-bios",bios,new byte[0],false));
        boolean[][] fits=new boolean[parts.size()][inventory.getSizeInventory()];
        for(int i=0;i<parts.size();i++) for(int s=0;s<inventory.getSizeInventory();s++) fits[i][s]=inventory.isItemValidForSlot(s,parts.get(i));
        int[] assignment=RunnerHardware.match(fits,inventory.getSizeInventory());
        if(assignment==null) throw new IllegalArgumentException("computer hardware does not fit native case tier "+h.get("tier")+" slots: "+h);
        ItemStack drive=storage.get(h.get("bootDrive").getAsInt());
        program.provision(spec.getAsJsonObject("program").get("entry").getAsString(),bios,drive);
        for(int i=0;i<parts.size();i++) inventory.setInventorySlotContents(assignment[i],parts.get(i));
        tile.getClass().getMethod("connectComponents").invoke(tile);
        machine=(Machine)tile.getClass().getMethod("machine").invoke(tile);
        RunnerScheduler.attachMachine((Runnable)machine);
    }
    private ItemStack part(String name,String kind) {
        ItemStack stack=RunnerHardware.oc(name);
        li.cil.oc.api.driver.DriverItem driver=li.cil.oc.api.Driver.driverFor(stack,tile.getClass().asSubclass(li.cil.oc.api.network.EnvironmentHost.class));
        if(driver==null || !kind.equals(driver.slot(stack))) throw new IllegalArgumentException("computer hardware "+name+" is not native case "+kind);
        return stack;
    }
    boolean prepare(long tick) throws Exception {
        if(started) return true;
        if(tick<3 || machine.node().network()==null) return false;
        IInventory inventory=(IInventory)tile;
        // Borrow the actual configured HDD environment, exactly like RunnerProgram's robot observer.
        scala.Option<?>[] components=(scala.Option<?>[])tile.getClass().getMethod("components").invoke(tile);
        program.observeNativeDrive(inventory,slot -> slot<components.length && components[slot].isDefined()?components[slot].get():null);
        if(!machine.start()) throw new IllegalStateException("computer would not start: "+machine.lastError());
        started=true;return true;
    }
    String tick() throws Exception {
        if(world.getTileEntity(tile.getPos())!=tile) return "computer_error:case removed";
        String outcome=program.outcome();
        if(outcome.startsWith("returned\n")) {status="returned";return "returned";}
        if(outcome.startsWith("error\n")) {status="error";message=outcome.substring(6);return "computer_program_error:"+message;}
        String state=state();if(RunnerRuntime.needsNativeClose(state)) li.cil.oc.common.EventHandler$.MODULE$.scheduleClose((li.cil.oc.server.machine.Machine)machine);
        if(machine.lastError()!=null) return "computer_error:"+machine.lastError();
        if(state.equals("Stopped")) return "computer_program_not_returned";
        return null;
    }
    private String state() throws Exception {
        Field field=machine.getClass().getDeclaredField("state");field.setAccessible(true);Object stack=field.get(machine);
        synchronized(stack) {return String.valueOf(stack.getClass().getMethod("top").invoke(stack));}
    }
    JsonObject snapshot() throws Exception {
        JsonObject value=new JsonObject();value.add("position",RunnerObservations.coords(tile.getPos()));value.addProperty("state",state());
        value.addProperty("lastError",machine.lastError());value.addProperty("energy",((Connector)machine.node()).globalBuffer());
        value.addProperty("energyCapacity",((Connector)machine.node()).globalBufferSize());value.add("program",programResult());return value;
    }
    JsonObject programResult() {JsonObject v=new JsonObject();v.addProperty("status",status);v.addProperty("message",message.substring(0,Math.min(8192,message.length())));return v;}
    void close() throws Exception {try {if(program.observing()) program.exportConsole();} finally {program.close();}}
}
