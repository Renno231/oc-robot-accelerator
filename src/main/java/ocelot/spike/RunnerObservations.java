package ocelot.spike;

import com.google.gson.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import li.cil.oc.api.internal.Robot;
import li.cil.oc.api.network.Connector;
import net.minecraft.block.Block;
import net.minecraft.block.properties.IProperty;
import net.minecraft.block.state.IBlockState;
import net.minecraft.item.ItemStack;
import net.minecraft.tileentity.TileEntity;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.WorldServer;

/** END tick samples: initial full region, later changed cells, capped UTF-8 NDJSON. */
final class RunnerObservations implements Closeable {
    private final RunnerScenario spec;
    private final WorldServer world;
    private final Robot robot;
    private final RunnerRecording recording;
    private final Map<BlockPos,IBlockState> previous=new HashMap<>();
    private long sequence;
    private final StallClock stallClock=new StallClock();
    RunnerObservations(RunnerScenario spec,WorldServer world,Robot robot,Path root) throws IOException {
        this.spec=spec;this.world=world;this.robot=robot;
        recording=new RunnerRecording(root,spec.maxBytes,spec.onFull);
    }
    JsonObject robot(String state) {
        JsonObject value=new JsonObject();BlockPos p=((TileEntity)robot).getPos();
        value.add("position",coords(p));value.addProperty("facing",robot.facing().toString().toLowerCase(Locale.ROOT));
        value.addProperty("energy",((Connector)robot.machine().node()).globalBuffer());value.addProperty("state",state);
        JsonArray inventory=new JsonArray();
        for(int slot=0;slot<robot.mainInventory().getSizeInventory();slot++) {
            ItemStack stack=robot.mainInventory().getStackInSlot(slot);
            if(!stack.isEmpty()) {JsonObject item=stack(stack);item.addProperty("slot",slot+1);inventory.add(item);}
        }
        value.add("inventory",inventory);value.add("tool",stack(robot.getStackInSlot(0)));
        if(spec.hardware!=null) {
            value.addProperty("energyCapacity",((Connector)robot.machine().node()).globalBufferSize());
            value.addProperty("inventoryCapacity",robot.mainInventory().getSizeInventory());
            JsonArray experience=new JsonArray();
            for(int slot=0;slot<robot.getSizeInventory();slot++) {
                Object component=robot.getComponentInSlot(slot);
                if(component instanceof li.cil.oc.server.component.UpgradeExperience) {
                    li.cil.oc.server.component.UpgradeExperience upgrade=(li.cil.oc.server.component.UpgradeExperience)component;
                    JsonObject xp=new JsonObject();xp.addProperty("level",upgrade.level());xp.addProperty("experience",upgrade.experience());
                    experience.add(xp);
                }
            }
            value.add("experienceUpgrades",experience);
        }
        return value;
    }
    private static JsonObject stack(ItemStack stack) {
        JsonObject item=new JsonObject();
        item.addProperty("item",stack.isEmpty()?"minecraft:air":String.valueOf(stack.getItem().getRegistryName()));
        item.addProperty("count",stack.isEmpty()?0:stack.getCount());item.addProperty("metadata",stack.isEmpty()?0:stack.getItemDamage());
        item.addProperty("nbt",stack.hasTagCompound()?stack.getTagCompound().toString():"{}");return item;
    }
    static JsonArray coords(BlockPos pos) {JsonArray a=new JsonArray();a.add(pos.getX());a.add(pos.getY());a.add(pos.getZ());return a;}
    static BlockPos pos(int[] p) {return new BlockPos(p[0],p[1],p[2]);}
    static JsonObject changedBlock(Map<BlockPos,IBlockState> previous,BlockPos pos,IBlockState state) {
        // Native block states are immutable. Compare before constructing JSON for
        // the overwhelmingly common unchanged cell; wire content is identical.
        if(state.equals(previous.put(pos,state))) return null;
        JsonObject value=new JsonObject();value.add("position",coords(pos));
        value.addProperty("block",String.valueOf(state.getBlock().getRegistryName()));JsonObject properties=new JsonObject();
        for(Map.Entry<IProperty<?>,Comparable<?>> e:state.getProperties().entrySet()) properties.addProperty(e.getKey().getName(),property(e.getKey(),e.getValue()));
        value.add("properties",properties);return value;
    }
    @SuppressWarnings({"unchecked","rawtypes"}) private static String property(IProperty p,Comparable value) {return p.getName(value);}
    void sample(String kind,long tick,String state) throws IOException {
        JsonObject value=new JsonObject();value.addProperty("schemaVersion",1);value.addProperty("sequence",sequence);
        value.addProperty("tick",tick);value.addProperty("kind",kind);
        if(kind.equals("initial")) {
            JsonObject bounds=new JsonObject();bounds.add("min",coords(pos(spec.min)));bounds.add("max",coords(pos(spec.max)));
            value.add("region",bounds);value.addProperty("everyTicks",spec.everyTicks);
        }
        JsonArray changes=new JsonArray();
        for(int x=spec.min[0];x<=spec.max[0];x++) for(int y=spec.min[1];y<=spec.max[1];y++) for(int z=spec.min[2];z<=spec.max[2];z++) {
            BlockPos p=new BlockPos(x,y,z);JsonObject changed=changedBlock(previous,p,world.getBlockState(p));
            if(changed!=null) changes.add(changed);
        }
        value.add("blocks",changes);JsonObject r=robot(state);value.add("robot",r);
        // The engine still scans the region and robot after the retained prefix stops.
        if(recording.record(value.toString(),kind,tick)) sequence++;
        // Stall policy observes selected robot state and changed sampled region, not Lua progress.
        String fingerprint=r.get("position")+"|"+r.get("facing")+"|"+r.get("energy")+"|"+r.get("inventory")+"|"+r.get("tool");
        stallClock.observe(tick,fingerprint,changes.size()>0);
    }
    static byte[] wireLine(String line) {
        byte[] utf8=line.getBytes(StandardCharsets.UTF_8);
        byte[] encoded=Arrays.copyOf(utf8,utf8.length+1);encoded[utf8.length]='\n';return encoded;
    }
    static final class StallClock {
        private String lastRobot;
        private long lastChangeTick;
        long observe(long tick,String robot,boolean regionChanged) {
            if(!robot.equals(lastRobot) || regionChanged) lastChangeTick=tick;
            lastRobot=robot;
            return lastChangeTick;
        }
        long lastChangeTick() {return lastChangeTick;}
    }
    boolean stalled(long tick) {return spec.stallTicks>0 && tick-stallClock.lastChangeTick()>=spec.stallTicks;}
    JsonObject coverage() {return recording.coverage();}
    @Override public void close() throws IOException {recording.close();}
}
