package ocelot.spike;

import com.google.gson.*;
import java.util.HashSet;
import java.util.Set;
import net.minecraft.inventory.IInventory;
import net.minecraft.world.WorldServer;

/** One-shot scenario-declared player removals through native inventory APIs. */
final class RunnerContainerEdits {
    private final JsonArray edits;
    private final Set<Integer> applied=new HashSet<>();
    RunnerContainerEdits(JsonArray edits) {this.edits=edits;}
    static void remove(IInventory inventory,JsonObject edit) {
        int slot=edit.get("slot").getAsInt()-1,count=edit.get("count").getAsInt();
        if(slot>=inventory.getSizeInventory()) throw new IllegalStateException("container_edit_slot_capacity");
        int actual=inventory.getStackInSlot(slot).getCount();
        if(actual<count || (edit.has("expectedCount") && actual!=edit.get("expectedCount").getAsInt()))
            throw new IllegalStateException("container_edit_source_count:"+actual);
        if(inventory.decrStackSize(slot,count).getCount()!=count) throw new IllegalStateException("container_edit_removal_count");
        inventory.markDirty();
    }
    void tick(long tick,WorldServer world,RunnerComputer computer,RunnerComputer second) {
        for(int index=0;index<edits.size();index++) {
            if(applied.contains(index)) continue;
            JsonObject edit=edits.get(index).getAsJsonObject();RunnerComputer controller=null;
            if(edit.has("atTick")) {if(tick<edit.get("atTick").getAsLong()) continue;}
            else {
                JsonObject request=edit.getAsJsonObject("request");
                controller=request.get("computer").getAsInt()==0?computer:second;
                if(!controller.markerRequested(request.get("marker").getAsString())) continue;
            }
            remove(RunnerContainers.inventory(world,RunnerContainers.pos(edit)),edit);applied.add(index);
            if(controller!=null) controller.signal(edit.getAsJsonObject("request").get("signal").getAsString());
        }
    }
}
