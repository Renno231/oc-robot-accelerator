package ocelot.spike;

import com.google.gson.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.zip.GZIPInputStream;
import li.cil.oc.api.internal.Robot;
import net.minecraft.inventory.IInventory;
import net.minecraft.init.Blocks;
import net.minecraft.item.Item;
import net.minecraft.item.ItemStack;
import net.minecraft.tileentity.TileEntityChest;
import net.minecraft.tileentity.TileEntity;
import net.minecraft.util.ResourceLocation;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.WorldServer;

/** Opt-in full-build fixture. Finite bulk backing feeds a normal native chest;
 * robot withdrawals still use OC's native inventory-controller transfer. */
final class RunnerFullBuild {
    final JsonObject config;
    final long[] remaining;
    final Item[] items;
    final BlockPos chest;
    private int x,y,z,xMin,xMax,yMin,yMax,zMin,zMax;
    private boolean initialized,prepared;
    private boolean recoveryRobotRemoved;
    private InputStream recoveryExpected;
    private long recoveredBlocks;
    private final long[] reclaimed;
    RunnerFullBuild(JsonObject config) {
        this.config=config;chest=RunnerObservations.pos(RunnerScenario.position(config.get("chest")));
        JsonArray materials=config.getAsJsonArray("materials");
        remaining=new long[materials.size()];items=new Item[materials.size()];reclaimed=new long[materials.size()];
        for(int i=0;i<items.length;i++) {
            JsonObject m=materials.get(i).getAsJsonObject();ResourceLocation id=new ResourceLocation(m.get("item").getAsString());
            if(!Item.REGISTRY.containsKey(id))throw new IllegalArgumentException("bulk material missing: "+id);
            items[i]=Item.REGISTRY.getObject(id);remaining[i]=m.get("count").getAsLong();
        }
    }
    private void reclaim(IInventory inventory) {
        for(int slot=0;slot<inventory.getSizeInventory();slot++) {
            ItemStack stack=inventory.getStackInSlot(slot);
            for(int i=0;i<items.length;i++)if(!stack.isEmpty() && stack.getItem()==items[i])reclaimed[i]+=stack.getCount();
        }
        inventory.clear();
    }
    void removeRecoveryRobot(WorldServer world) throws Exception {
        if(!config.has("resume") || recoveryRobotRemoved)return;
        BlockPos p=RunnerObservations.pos(RunnerScenario.position(config.getAsJsonObject("resume").get("robot")));
        TileEntity tile=world.getTileEntity(p);
        if(tile==null || !tile.getClass().getName().equals("li.cil.oc.common.tileentity.RobotProxy"))
            throw new IllegalStateException("recovery expected native OC robot missing: "+p);
        Robot old=(Robot)tile.getClass().getMethod("robot").invoke(tile);
        old.machine().stop();reclaim(old.mainInventory());
        // Remove the validated proxy first so the block break cannot scatter
        // reclaimed stock into the world. The source world is a frozen copy.
        world.removeTileEntity(p);world.setBlockToAir(p);
        TileEntity stock=world.getTileEntity(chest);
        if(!(stock instanceof TileEntityChest))throw new IllegalStateException("recovery chest missing");
        reclaim((IInventory)stock);recoveryRobotRemoved=true;
    }
    boolean setup(WorldServer world,RunnerScenario spec,Path root) throws IOException {
        int[] lo=RunnerScenario.position(config.get("min")),hi=RunnerScenario.position(config.get("max"));
        if(prepared)return true;
        if(config.has("resume"))return recover(world,root,lo,hi);
        if(!initialized){
            xMin=Math.min(lo[0]-1,spec.min[0]);xMax=Math.max(hi[0]+1,spec.max[0]);
            zMin=Math.min(lo[2]-1,spec.min[2]);zMax=Math.max(hi[2]+1,spec.max[2]);
            yMin=lo[1]-1;yMax=Math.min(254,Math.max(hi[1]+1,spec.max[1]));
            x=xMin;z=zMin;y=yMin;initialized=true;
        }
        long deadline=System.nanoTime()+20000000L;
        // Work space is empty; source blocks are never inserted by the fixture.
        // Spread large fixture preparation over ticks instead of monopolizing a
        // server tick. This bounds responsiveness, not the allowed build size.
        while(x<=xMax){
            BlockPos p=new BlockPos(x,y,z);
            if(y==yMin)world.setBlockState(p,Blocks.STONE.getDefaultState(),2);
            else if(!world.isAirBlock(p))world.setBlockToAir(p);
            if(++y>yMax){y=yMin;if(++z>zMax){z=zMin;x++;}}
            if(System.nanoTime()>=deadline)return false;
        }
        prepared=true;return true;
    }
    private boolean recover(WorldServer world,Path root,int[] lo,int[] hi) throws IOException {
        if(!initialized) {
            xMin=lo[0];xMax=hi[0];yMin=lo[1];yMax=hi[1];zMin=lo[2];zMax=hi[2];
            x=xMin;y=yMin;z=zMin;initialized=true;
            Path path=root.resolve("program").resolve(config.get("expected").getAsString()).normalize();
            if(!path.startsWith(root.resolve("program")))throw new IOException("recovery expected path");
            recoveryExpected=new BufferedInputStream(new GZIPInputStream(Files.newInputStream(path)));
        }
        JsonArray palette=config.getAsJsonArray("palette");long deadline=System.nanoTime()+20000000L;
        // Preserve every construction block. Independently verify the imported
        // world and reconcile its finite stock budget with the original source.
        while(y<=yMax) {
            int id=recoveryExpected.read();if(id<0 || id>=palette.size())throw new IOException("recovery expected stream");
            String target=palette.get(id).getAsString();BlockPos p=new BlockPos(x,y,z);
            String actual=String.valueOf(world.getBlockState(p).getBlock().getRegistryName());
            if(!actual.equals("minecraft:air")) {
                if(!actual.equals(target))throw new IOException("recovery foreign block: "+p+" "+actual+" != "+target);
                boolean material=false;
                for(int i=0;i<items.length;i++)if(actual.equals(String.valueOf(items[i].getRegistryName()))) {
                    if(--remaining[i]<0)throw new IOException("recovery material budget exceeded");
                    material=true;break;
                }
                if(!material)throw new IOException("recovery material not in finite source budget: "+actual);
                recoveredBlocks++;
            }
            if(++x>xMax){x=xMin;if(++z>zMax){z=zMin;y++;}}
            if(System.nanoTime()>=deadline)return false;
        }
        if(recoveryExpected.read()!=-1)throw new IOException("recovery expected trailing data");
        recoveryExpected.close();recoveryExpected=null;
        if(recoveredBlocks!=config.getAsJsonObject("resume").get("builtBlocks").getAsLong())
            throw new IOException("recovery census changed: "+recoveredBlocks);
        JsonObject report=new JsonObject();report.addProperty("preservedBlocks",recoveredBlocks);
        JsonArray stock=new JsonArray();
        for(int i=0;i<items.length;i++) {
            if(reclaimed[i]>remaining[i])throw new IOException("recovery resident stock exceeds remaining source budget");
            JsonObject m=new JsonObject();m.addProperty("item",String.valueOf(items[i].getRegistryName()));
            m.addProperty("remainingSourceBudget",remaining[i]);m.addProperty("reclaimedResidentStock",reclaimed[i]);stock.add(m);
        }
        report.add("materials",stock);
        Files.write(root.resolve("full-build-recovery.json"),report.toString().getBytes(StandardCharsets.UTF_8));
        prepared=true;return true;
    }
    void refill(WorldServer world) {
        TileEntityChest inventory=(TileEntityChest)world.getTileEntity(chest);
        if(inventory==null)throw new IllegalStateException("bulk chest unavailable");
        int returns=config.has("returnSlots")?config.get("returnSlots").getAsInt():0;
        for(int slot=0;slot<inventory.getSizeInventory();slot++) {
            ItemStack stack=inventory.getStackInSlot(slot);
            if(stack.isEmpty())continue;
            // A real controller can choose any available native chest slot.
            // Reclaim misplaced declared material as well as designated returns.
            if(slot<inventory.getSizeInventory()-returns && stack.getItem()==items[slot%items.length] && stack.getMetadata()==0)continue;
            int material=-1;
            for(int i=0;i<items.length;i++)if(stack.getItem()==items[i] && stack.getMetadata()==0)material=i;
            if(material<0)throw new IllegalStateException("unsupported bulk material return");
            remaining[material]=Math.addExact(remaining[material],stack.getCount());
            inventory.setInventorySlotContents(slot,ItemStack.EMPTY);inventory.markDirty();
        }
        for(int slot=0;slot<inventory.getSizeInventory()-returns;slot++) {
            int i=slot%items.length;ItemStack stack=inventory.getStackInSlot(slot);
            if(!stack.isEmpty() && stack.getItem()!=items[i])throw new IllegalStateException("bulk chest slot changed");
            int have=stack.isEmpty()?0:stack.getCount();int add=(int)Math.min(remaining[i],items[i].getItemStackLimit()-have);
            if(add>0){inventory.setInventorySlotContents(slot,new ItemStack(items[i],have+add));remaining[i]-=add;inventory.markDirty();}
        }
    }
    boolean verify(WorldServer world,Path root) throws IOException {
        int[] lo=RunnerScenario.position(config.get("min")),hi=RunnerScenario.position(config.get("max"));
        JsonArray palette=config.getAsJsonArray("palette"),examples=new JsonArray();
        long checked=0,nonAir=0,mismatches=0;
        Path expected=root.resolve("program").resolve(config.get("expected").getAsString()).normalize();
        if(!expected.startsWith(root.resolve("program")))throw new IOException("expected path outside program");
        try(InputStream in=new BufferedInputStream(new GZIPInputStream(Files.newInputStream(expected)))) {
            for(int y=lo[1];y<=hi[1];y++)for(int z=lo[2];z<=hi[2];z++)for(int x=lo[0];x<=hi[0];x++) {
                int id=in.read();if(id<0 || id>=palette.size())throw new IOException("expected data truncated/invalid");
                String target=palette.get(id).getAsString();BlockPos p=new BlockPos(x,y,z);
                String actual=String.valueOf(world.getBlockState(p).getBlock().getRegistryName());
                checked++;if(!target.equals("minecraft:air"))nonAir++;
                if(!target.equals(actual)){mismatches++;if(examples.size()<20){JsonObject e=new JsonObject();e.add("position",RunnerObservations.coords(p));e.addProperty("expected",target);e.addProperty("actual",actual);examples.add(e);}}
            }
            if(in.read()!=-1)throw new IOException("expected data trailing bytes");
        }
        JsonObject result=new JsonObject();result.addProperty("checkedCells",checked);result.addProperty("expectedNonAir",nonAir);
        result.addProperty("mismatches",mismatches);result.add("examples",examples);
        JsonArray stock=new JsonArray();for(int i=0;i<items.length;i++){JsonObject e=new JsonObject();e.addProperty("item",String.valueOf(items[i].getRegistryName()));e.addProperty("bulkRemaining",remaining[i]);stock.add(e);}result.add("stock",stock);
        Files.write(root.resolve("full-build-verification.json"),result.toString().getBytes(StandardCharsets.UTF_8));
        return mismatches==0;
    }
}
