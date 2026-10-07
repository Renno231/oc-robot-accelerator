package ocelot.spike;

import com.google.gson.*;
import net.minecraft.inventory.IInventory;
import net.minecraft.item.ItemStack;
import net.minecraft.tileentity.TileEntity;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.WorldServer;

/** Declared block inventories, using physical tile slots rather than merged chest views. */
final class RunnerContainers {
    static BlockPos pos(JsonObject c) {return RunnerObservations.pos(RunnerScenario.position(c.get("position")));}
    static IInventory inventory(WorldServer world,BlockPos p) {
        TileEntity tile=world.getTileEntity(p);
        if(!(tile instanceof IInventory)) throw new IllegalArgumentException("container has no native inventory: "+p);
        return (IInventory)tile;
    }
    static void fill(IInventory inventory,JsonArray slots,String label) throws Exception {
        for(JsonElement e:slots) {
            JsonObject i=e.getAsJsonObject();int slot=i.get("slot").getAsInt()-1;
            if(slot>=inventory.getSizeInventory()) throw new IllegalArgumentException(label+" slot exceeds native capacity: "+(slot+1));
            ItemStack stack=RunnerRuntime.item(i,i.get("count").getAsInt());
            if(stack.getCount()>inventory.getInventoryStackLimit() || !inventory.isItemValidForSlot(slot,stack))
                throw new IllegalArgumentException(label+" invalid native slot: "+(slot+1));
            inventory.setInventorySlotContents(slot,stack);
        }
        inventory.markDirty();
    }
    static void setup(RunnerScenario spec,WorldServer world) throws Exception {
        if(spec.v4==null) return;
        for(JsonElement e:spec.v4.containers) {
            JsonObject c=e.getAsJsonObject();JsonObject block=new JsonObject();block.add("block",c.get("block"));block.add("properties",c.has("properties")?c.get("properties"):new JsonObject());
            world.setBlockState(pos(c),RunnerRuntime.blockState(block),3);
            IInventory inventory=inventory(world,pos(c));inventory.clear();fill(inventory,c.getAsJsonArray("slots"),"container "+pos(c));
        }
    }
    static JsonArray contents(IInventory inventory) {
        JsonArray result=new JsonArray();
        for(int s=0;s<inventory.getSizeInventory();s++) {
            ItemStack stack=inventory.getStackInSlot(s);if(stack.isEmpty()) continue;
            JsonObject item=new JsonObject();item.addProperty("slot",s+1);item.addProperty("item",String.valueOf(stack.getItem().getRegistryName()));
            item.addProperty("count",stack.getCount());item.addProperty("metadata",stack.getItemDamage());item.addProperty("nbt",stack.hasTagCompound()?stack.getTagCompound().toString():"{}");result.add(item);
        }
        return result;
    }
    static String checkSlots(IInventory inventory,JsonArray slots,String label) {
        for(JsonElement e:slots) {
            JsonObject i=e.getAsJsonObject();int slot=i.get("slot").getAsInt()-1,count=i.get("count").getAsInt();
            if(slot>=inventory.getSizeInventory()) return "expectation_failed:"+label+" slot "+(slot+1)+" exceeds native capacity";
            ItemStack stack=inventory.getStackInSlot(slot);
            boolean empty=count==0 || !i.has("item");
            if(empty?!stack.isEmpty():stack.isEmpty() || stack.getCount()!=count || !String.valueOf(stack.getItem().getRegistryName()).equals(i.get("item").getAsString()))
                return "expectation_failed:"+label+" slot "+(slot+1)+" expected "+i+" actual "+stack;
        }
        return null;
    }
    static String assertions(RunnerScenario spec,WorldServer world) {
        if(spec.v4==null) return null;
        for(JsonElement e:spec.v4.expectedContainers) {
            JsonObject c=e.getAsJsonObject();String error;
            try {error=checkSlots(inventory(world,pos(c)),c.getAsJsonArray("slots"),"container "+pos(c));}
            catch(IllegalArgumentException ex) {return "expectation_failed:container "+pos(c)+" missing native inventory";}
            if(error!=null) return error;
        }
        return null;
    }
    static JsonArray result(RunnerScenario spec,WorldServer world) {
        JsonArray result=new JsonArray();
        if(spec.v4!=null) for(JsonElement e:spec.v4.containers) {
            JsonObject c=e.getAsJsonObject(),value=new JsonObject();BlockPos p=pos(c);
            value.add("position",RunnerObservations.coords(p));value.addProperty("block",String.valueOf(world.getBlockState(p).getBlock().getRegistryName()));
            try {value.add("slots",contents(inventory(world,p)));} catch(IllegalArgumentException ex) {value.addProperty("error",ex.getMessage());}
            result.add(value);
        }
        return result;
    }
}
