package ocelot.spike;

import com.google.gson.*;
import com.mojang.authlib.GameProfile;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.file.Path;
import java.util.*;
import li.cil.oc.api.internal.Robot;
import li.cil.oc.api.network.Connector;
import net.minecraft.block.Block;
import net.minecraft.item.ItemStack;
import net.minecraft.tileentity.TileEntity;
import net.minecraft.util.EnumFacing;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.WorldServer;
import net.minecraftforge.common.util.FakePlayer;
import net.minecraftforge.common.util.FakePlayerFactory;

/** One native assembled OpenOS robot in the v4 multi-host runner. */
final class RunnerRobot {
    private final JsonObject spec;
    private final WorldServer world;
    private final RunnerProgram program;
    private Robot robot;
    private boolean started;
    private String status="not_returned",message="";
    RunnerRobot(JsonObject spec,WorldServer world,Path root) {
        this.spec=spec;this.world=world;
        program=new RunnerProgram(root,spec.getAsJsonObject("program").get("directory").getAsString());
    }
    boolean owns(TileEntity tile) {
        return robot!=null && tile.getWorld()==world && tile.getPos().equals(((TileEntity)robot).getPos());
    }
    void setup() throws Exception {
        BlockPos p=RunnerContainers.pos(spec);
        if(!world.isAirBlock(p)) throw new IllegalArgumentException("robot_cell_not_air:"+p);
        byte[] bios;
        try(InputStream input=getClass().getClassLoader().getResourceAsStream("assets/opencomputers/lua/bios.lua")) {
            if(input==null) throw new IOException("Pinned OC BIOS absent");
            ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[4096];int n;
            while((n=input.read(buffer))!=-1) {out.write(buffer,0,n);if(out.size()>li.cil.oc.Settings.get().eepromSize()) throw new IOException("OC BIOS EEPROM bound");}
            bios=out.toByteArray();
        }
        ItemStack firmware=li.cil.oc.api.Items.registerEEPROM("runner-robot-bios",bios,new byte[0],false);
        RunnerHardware hardware=RunnerHardware.assemble(spec.getAsJsonObject("hardware"),firmware);
        program.provision(spec.getAsJsonObject("program").get("entry").getAsString(),bios,hardware.bootDrive);
        hardware.data.name_$eq("runner-robot");
        int energy=(int)Math.ceil(spec.get("energy").getAsDouble());
        hardware.data.robotEnergy_$eq(energy);hardware.data.totalEnergy_$eq(energy);
        ItemStack stack=hardware.data.createItemStack();Block block=Block.getBlockFromItem(stack.getItem());
        world.setBlockState(p,block.getDefaultState(),3);
        FakePlayer owner=FakePlayerFactory.get(world,new GameProfile(UUID.fromString("933cfa95-d269-48dd-8ed0-3c38ef1983fa"),"spike-owner"));
        owner.setPosition(p.getX()+0.5,p.getY(),p.getZ()+0.5);owner.rotationYaw=180;
        block.onBlockPlacedBy(world,p,world.getBlockState(p),owner,stack);
        Object proxy=world.getTileEntity(p);robot=(Robot)proxy.getClass().getMethod("robot").invoke(proxy);
        robot.getClass().getMethod("setFromFacing",EnumFacing.class).invoke(robot,EnumFacing.valueOf(spec.get("facing").getAsString().toUpperCase(Locale.ROOT)));
        hardware.equip(robot);robot.getClass().getMethod("connectComponents").invoke(robot);
        RunnerContainers.fill(robot.mainInventory(),spec.getAsJsonArray("inventory"),"robot");
        RunnerScheduler.attachMachine((Runnable)robot.machine());
    }
    boolean prepare(long tick) throws Exception {
        if(started) return true;
        if(tick<3 || robot.node().network()==null) return false;
        Connector power=(Connector)robot.machine().node();double energy=spec.get("energy").getAsDouble();
        if(energy>power.globalBufferSize()) throw new IllegalArgumentException("robot energy exceeds native capacity: "+power.globalBufferSize());
        power.changeBuffer(energy-power.globalBuffer());
        program.observeNativeDrive(robot);
        if(!robot.machine().start()) throw new IllegalStateException("robot would not start: "+robot.machine().lastError());
        started=true;return true;
    }
    String tick() throws Exception {
        TileEntity proxy=world.getTileEntity(((TileEntity)robot).getPos());
        if(proxy==null || !proxy.getClass().getName().equals("li.cil.oc.common.tileentity.RobotProxy") ||
                proxy.getClass().getMethod("robot").invoke(proxy)!=robot) return "robot_error:robot removed";
        String outcome=program.outcome();
        if(outcome.startsWith("returned\n")) status="returned";
        else if(outcome.startsWith("error\n")) {status="error";message=outcome.substring(6);return "robot_program_error:"+message;}
        String state=state();
        if(RunnerRuntime.needsNativeClose(state)) li.cil.oc.common.EventHandler$.MODULE$.scheduleClose((li.cil.oc.server.machine.Machine)robot.machine());
        if(robot.machine().lastError()!=null) return "robot_error:"+robot.machine().lastError();
        if(state.equals("Stopped")) return status.equals("returned")?"returned":"robot_program_not_returned";
        return null;
    }
    private String state() throws Exception {
        Field field=robot.machine().getClass().getDeclaredField("state");field.setAccessible(true);Object stack=field.get(robot.machine());
        synchronized(stack) {return String.valueOf(stack.getClass().getMethod("top").invoke(stack));}
    }
    String checkInventory(JsonArray expected) {return RunnerContainers.checkSlots(robot.mainInventory(),expected,"robot inventory");}
    JsonObject snapshot(int index) throws Exception {
        JsonObject value=new JsonObject();value.addProperty("index",index);
        value.add("position",RunnerObservations.coords(((TileEntity)robot).getPos()));
        value.addProperty("facing",robot.facing().getName());value.addProperty("state",state());
        value.addProperty("lastError",robot.machine().lastError());
        Connector power=(Connector)robot.machine().node();value.addProperty("energy",power.globalBuffer());value.addProperty("energyCapacity",power.globalBufferSize());
        value.add("inventory",RunnerContainers.contents(robot.mainInventory()));value.addProperty("inventoryCapacity",robot.mainInventory().getSizeInventory());
        JsonObject result=new JsonObject();result.addProperty("status",status);result.addProperty("message",message.substring(0,Math.min(8192,message.length())));
        value.add("program",result);return value;
    }
    void close() throws Exception {try {if(program.observing()) program.exportConsole();} finally {program.close();}}
}
