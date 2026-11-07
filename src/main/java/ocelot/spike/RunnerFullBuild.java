package ocelot.spike;

import com.google.gson.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.zip.GZIPInputStream;
import li.cil.oc.api.internal.Robot;
import net.minecraft.block.state.IBlockState;
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
    /** Stocked kinds: item and metadata, count 1. */
    final ItemStack[] items;
    final BlockPos chest;
    /** A further robot's stocked chest with its own finite budget. */
    private static final class Stock {
        final BlockPos chest;final ItemStack[] items;final long[] remaining;
        Stock(BlockPos chest,ItemStack[] items,long[] remaining){this.chest=chest;this.items=items;this.remaining=remaining;}
    }
    private final List<Stock> extra=new ArrayList<>();
    private int x,y,z,xMin,xMax,yMin,yMax,zMin,zMax;
    private boolean initialized,prepared;
    private boolean recoveryRobotRemoved;
    private InputStream recoveryExpected;
    private long recoveredBlocks;
    private final long[] reclaimed;
    /** Items returned to a stock chest that are not build stock (a terrain build's dug spoil), by item. */
    private final Map<String,Long> spoils=new TreeMap<>();
    /** The program directory holding the expected world: robot 0's when several robots build. */
    private final String program;
    RunnerFullBuild(JsonObject config,String program) {
        this.config=config;this.program=program;chest=RunnerObservations.pos(RunnerScenario.position(config.get("chest")));
        JsonArray materials=config.getAsJsonArray("materials");
        remaining=new long[materials.size()];items=new ItemStack[materials.size()];reclaimed=new long[materials.size()];
        stock(materials,items,remaining);
        if(config.has("extraChests"))for(JsonElement e:config.getAsJsonArray("extraChests")) {
            JsonObject c=e.getAsJsonObject();JsonArray m=c.getAsJsonArray("materials");
            ItemStack[] i=new ItemStack[m.size()];long[] r=new long[m.size()];stock(m,i,r);
            extra.add(new Stock(RunnerObservations.pos(RunnerScenario.position(c.get("position"))),i,r));
        }
    }
    private static void stock(JsonArray materials,ItemStack[] items,long[] remaining) {
        for(int i=0;i<items.length;i++) {
            JsonObject m=materials.get(i).getAsJsonObject();ResourceLocation id=new ResourceLocation(m.get("item").getAsString());
            if(!Item.REGISTRY.containsKey(id))throw new IllegalArgumentException("bulk material missing: "+id);
            items[i]=new ItemStack(Item.REGISTRY.getObject(id),1,m.has("metadata")?m.get("metadata").getAsInt():0);remaining[i]=m.get("count").getAsLong();
        }
    }
    private static boolean same(ItemStack stack,ItemStack kind) {
        return !stack.isEmpty() && stack.getItem()==kind.getItem() && stack.getMetadata()==kind.getMetadata();
    }
    /** The stocked kind that places a palette target: same registry name and, when given, metadata. */
    private static boolean matches(String target,ItemStack kind) {
        int open=target.indexOf('[');if(open>=0)target=target.substring(0,open);
        int colon=target.lastIndexOf(':');boolean meta=colon>target.indexOf(':');
        return (meta?target.substring(0,colon):target).equals(String.valueOf(kind.getItem().getRegistryName())) &&
            (!meta || kind.getMetadata()==Integer.parseInt(target.substring(colon+1)));
    }
    /** Palette target: a registry name, optionally suffixed with ":metadata", optionally followed by listed block
     *  properties "[key=value,...]". With properties the metadata is the item damage the block drops (its variant),
     *  and only the listed properties are compared. */
    static boolean matches(String target,IBlockState state) {
        int open=target.indexOf('[');
        if(open>=0) {
            String base=target.substring(0,open);int colon=base.lastIndexOf(':');boolean meta=colon>base.indexOf(':');
            if(!(meta?base.substring(0,colon):base).equals(String.valueOf(state.getBlock().getRegistryName())))return false;
            if(meta && state.getBlock().damageDropped(state)!=Integer.parseInt(base.substring(colon+1)))return false;
            Map<String,String> actual=new HashMap<>();
            for(Map.Entry<net.minecraft.block.properties.IProperty<?>,Comparable<?>> e:state.getProperties().entrySet())
                actual.put(e.getKey().getName(),name(e.getKey(),e.getValue()));
            for(String pair:target.substring(open+1,target.length()-1).split(",")) {
                int eq=pair.indexOf('=');if(!pair.substring(eq+1).equals(actual.get(pair.substring(0,eq))))return false;
            }
            return true;
        }
        int colon=target.lastIndexOf(':');boolean meta=colon>target.indexOf(':');
        String name=meta?target.substring(0,colon):target;
        return name.equals(String.valueOf(state.getBlock().getRegistryName())) &&
            (!meta || state.getBlock().getMetaFromState(state)==Integer.parseInt(target.substring(colon+1)));
    }
    @SuppressWarnings({"unchecked","rawtypes"})
    private static String name(net.minecraft.block.properties.IProperty property,Comparable value) { return property.getName(value); }
    private void reclaim(IInventory inventory) {
        for(int slot=0;slot<inventory.getSizeInventory();slot++) {
            ItemStack stack=inventory.getStackInSlot(slot);
            for(int i=0;i<items.length;i++)if(same(stack,items[i]))reclaimed[i]+=stack.getCount();
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
            if(y==yMin)world.setBlockState(p,Blocks.GRASS.getDefaultState(),2);
            else if(!world.isAirBlock(p))world.setBlockToAir(p);
            if(++y>yMax){y=yMin;if(++z>zMax){z=zMin;x++;}}
            if(System.nanoTime()>=deadline)return false;
        }
        // Every stocked chest stands in the cleared rim; declared world blocks may also place the first.
        if(world.isAirBlock(chest))world.setBlockState(chest,Blocks.CHEST.getDefaultState(),3);
        for(Stock stock:extra)world.setBlockState(stock.chest,Blocks.CHEST.getDefaultState(),3);
        prepared=true;return true;
    }
    private boolean recover(WorldServer world,Path root,int[] lo,int[] hi) throws IOException {
        if(!initialized) {
            xMin=lo[0];xMax=hi[0];yMin=lo[1];yMax=hi[1];zMin=lo[2];zMax=hi[2];
            x=xMin;y=yMin;z=zMin;initialized=true;
            Path path=root.resolve(program).resolve(config.get("expected").getAsString()).normalize();
            if(!path.startsWith(root.resolve(program)))throw new IOException("recovery expected path");
            recoveryExpected=new BufferedInputStream(new GZIPInputStream(Files.newInputStream(path)));
        }
        JsonArray palette=config.getAsJsonArray("palette");long deadline=System.nanoTime()+20000000L;
        // Preserve every construction block. Independently verify the imported
        // world and reconcile its finite stock budget with the original source.
        while(y<=yMax) {
            int id=recoveryExpected.read();if(id<0 || id>=palette.size())throw new IOException("recovery expected stream");
            String target=palette.get(id).getAsString();BlockPos p=new BlockPos(x,y,z);
            IBlockState state=world.getBlockState(p);String actual=String.valueOf(state.getBlock().getRegistryName());
            if(!actual.equals("minecraft:air")) {
                if(!matches(target,state))throw new IOException("recovery foreign block: "+p+" "+actual+" != "+target);
                boolean material=false;
                for(int i=0;i<items.length;i++)if(matches(target,items[i])) {
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
            JsonObject m=new JsonObject();m.addProperty("item",String.valueOf(items[i].getItem().getRegistryName()));m.addProperty("metadata",items[i].getMetadata());
            m.addProperty("remainingSourceBudget",remaining[i]);m.addProperty("reclaimedResidentStock",reclaimed[i]);stock.add(m);
        }
        report.add("materials",stock);
        Files.write(root.resolve("full-build-recovery.json"),report.toString().getBytes(StandardCharsets.UTF_8));
        prepared=true;return true;
    }
    void refill(WorldServer world) {
        refill(world,chest,items,remaining);
        for(Stock stock:extra)refill(world,stock.chest,stock.items,stock.remaining);
    }
    private void refill(WorldServer world,BlockPos chest,ItemStack[] items,long[] remaining) {
        TileEntityChest inventory=(TileEntityChest)world.getTileEntity(chest);
        if(inventory==null)throw new IllegalStateException("bulk chest unavailable");
        int returns=config.has("returnSlots")?config.get("returnSlots").getAsInt():0;
        for(int slot=0;slot<inventory.getSizeInventory();slot++) {
            ItemStack stack=inventory.getStackInSlot(slot);
            if(stack.isEmpty())continue;
            // A real controller can choose any available native chest slot.
            // Reclaim misplaced declared material as well as designated returns.
            if(slot<inventory.getSizeInventory()-returns && same(stack,items[slot%items.length]))continue;
            int material=-1;
            for(int i=0;i<items.length;i++)if(same(stack,items[i]))material=i;
            if(material<0) {
                // Spoil the builder dug out: the chest takes it like a real dump chest; the report counts it.
                String key=String.valueOf(stack.getItem().getRegistryName())+(stack.getMetadata()!=0?":"+stack.getMetadata():"");
                spoils.merge(key,(long)stack.getCount(),Long::sum);
            }
            else remaining[material]=Math.addExact(remaining[material],stack.getCount());
            inventory.setInventorySlotContents(slot,ItemStack.EMPTY);inventory.markDirty();
        }
        for(int slot=0;slot<inventory.getSizeInventory()-returns;slot++) {
            int i=slot%items.length;ItemStack stack=inventory.getStackInSlot(slot);
            if(!stack.isEmpty() && !same(stack,items[i]))throw new IllegalStateException("bulk chest slot changed");
            int have=stack.isEmpty()?0:stack.getCount();int add=(int)Math.min(remaining[i],items[i].getMaxStackSize()-have);
            if(add>0){ItemStack next=items[i].copy();next.setCount(have+add);inventory.setInventorySlotContents(slot,next);remaining[i]-=add;inventory.markDirty();}
        }
    }
    boolean verify(WorldServer world,Path root) throws IOException {
        int[] lo=RunnerScenario.position(config.get("min")),hi=RunnerScenario.position(config.get("max"));
        JsonArray palette=config.getAsJsonArray("palette"),examples=new JsonArray();
        long checked=0,nonAir=0,mismatches=0;
        Path expected=root.resolve(program).resolve(config.get("expected").getAsString()).normalize();
        if(!expected.startsWith(root.resolve(program)))throw new IOException("expected path outside program");
        try(InputStream in=new BufferedInputStream(new GZIPInputStream(Files.newInputStream(expected)))) {
            for(int y=lo[1];y<=hi[1];y++)for(int z=lo[2];z<=hi[2];z++)for(int x=lo[0];x<=hi[0];x++) {
                int id=in.read();if(id<0 || id>=palette.size())throw new IOException("expected data truncated/invalid");
                String target=palette.get(id).getAsString();BlockPos p=new BlockPos(x,y,z);
                IBlockState state=world.getBlockState(p);String actual=String.valueOf(state.getBlock().getRegistryName());
                if(target.indexOf('[')>=0)actual=state.toString();
                else if(state.getBlock().getMetaFromState(state)!=0)actual+=":"+state.getBlock().getMetaFromState(state);
                checked++;if(!target.equals("minecraft:air"))nonAir++;
                if(!matches(target,state)){mismatches++;if(examples.size()<20){JsonObject e=new JsonObject();e.add("position",RunnerObservations.coords(p));e.addProperty("expected",target);e.addProperty("actual",actual);examples.add(e);}}
            }
            if(in.read()!=-1)throw new IOException("expected data trailing bytes");
        }
        JsonObject result=new JsonObject();result.addProperty("checkedCells",checked);result.addProperty("expectedNonAir",nonAir);
        result.addProperty("mismatches",mismatches);result.add("examples",examples);
        result.add("stock",stock(items,remaining));
        JsonObject returned=new JsonObject();for(Map.Entry<String,Long> e:spoils.entrySet())returned.addProperty(e.getKey(),e.getValue());
        result.add("spoils",returned);
        if(!extra.isEmpty()){JsonArray stocks=new JsonArray();for(Stock s:extra)stocks.add(stock(s.items,s.remaining));result.add("extraStock",stocks);}
        Files.write(root.resolve("full-build-verification.json"),result.toString().getBytes(StandardCharsets.UTF_8));
        return mismatches==0;
    }
    private static JsonArray stock(ItemStack[] items,long[] remaining) {
        JsonArray stock=new JsonArray();
        for(int i=0;i<items.length;i++){JsonObject e=new JsonObject();e.addProperty("item",String.valueOf(items[i].getItem().getRegistryName()));e.addProperty("metadata",items[i].getMetadata());e.addProperty("bulkRemaining",remaining[i]);stock.add(e);}
        return stock;
    }
}
