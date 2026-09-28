package ocelot.spike;

import com.google.gson.*;
import java.util.*;
import li.cil.oc.api.internal.Robot;
import li.cil.oc.common.item.data.RobotData;
import li.cil.oc.common.template.AssemblerTemplates;
import li.cil.oc.common.template.AssemblerTemplates$;
import net.minecraft.inventory.InventoryBasic;
import net.minecraft.item.ItemStack;

/** Builds a real OC assembler recipe; native drivers own slot, tier and complexity rules. */
final class RunnerHardware {
    final RobotData data;
    final ItemStack bootDrive;
    private final List<ItemStack> equipment;
    private RunnerHardware(RobotData data,ItemStack bootDrive,List<ItemStack> equipment) {
        this.data=data; this.bootDrive=bootDrive; this.equipment=equipment;
    }
    static ItemStack oc(String key) {
        li.cil.oc.api.detail.ItemInfo info=li.cil.oc.api.Items.get(key);
        if(info==null) throw new IllegalArgumentException("unknown OC hardware component: "+key);
        return info.createItemStack(1);
    }
    private static ItemStack configured(JsonElement component) {
        if(component.isJsonPrimitive()) return oc(component.getAsString());
        JsonObject spec=component.getAsJsonObject();
        ItemStack stack=oc(spec.get("item").getAsString());
        li.cil.oc.util.UpgradeExperience$ xp=li.cil.oc.util.UpgradeExperience$.MODULE$;
        double experience=spec.has("level")?xp.xpForLevel(spec.get("level").getAsInt()):spec.get("experience").getAsDouble();
        xp.setExperience(li.cil.oc.api.Driver.driverFor(stack,Robot.class).dataTag(stack),experience);
        return stack;
    }
    static RunnerHardware assemble(JsonObject hardware,ItemStack firmware) {
        InventoryBasic inventory=new InventoryBasic("runner assembly",false,22);
        ItemStack computerCase=oc("case"+hardware.get("tier").getAsString());
        inventory.setInventorySlotContents(0,computerCase);
        scala.Option<AssemblerTemplates.Template> selected=AssemblerTemplates$.MODULE$.select(computerCase);
        if(selected.isEmpty()) throw new IllegalStateException("native robot assembler template absent");
        AssemblerTemplates.Template template=selected.get();
        List<ItemStack> containers=new ArrayList<>(), suppliedEquipment=new ArrayList<>();
        for(JsonElement entry:hardware.getAsJsonArray("containers")) {
            JsonObject c=entry.getAsJsonObject(); containers.add(oc(c.get("item").getAsString()));
            suppliedEquipment.add(c.has("component")?configured(c.get("component")):ItemStack.EMPTY);
        }
        int[] containerAssignment=place(inventory,template.containerSlots(),1,containers,"containers");
        List<ItemStack> equipment=new ArrayList<>();
        for(int slot=0;slot<template.containerSlots().length;slot++) {
            for(int input=0;input<containerAssignment.length;input++)
                if(containerAssignment[input]==slot) equipment.add(suppliedEquipment.get(input));
        }
        place(inventory,template.upgradeSlots(),4,parts(hardware,"upgrades","upgrade"),"upgrades");
        List<ItemStack> components=new ArrayList<>();
        ItemStack cpu=oc(hardware.get("cpu").getAsString()); requireKind(cpu,"cpu"); components.add(cpu);
        components.addAll(parts(hardware,"memory","memory"));
        components.addAll(parts(hardware,"cards","card"));
        List<ItemStack> storage=parts(hardware,"storage","hdd");
        ItemStack bootDrive=storage.get(hardware.get("bootDrive").getAsInt());
        components.addAll(storage); components.add(firmware);
        place(inventory,template.componentSlots(),13,components,"components");
        scala.Tuple3<Object,net.minecraft.util.text.ITextComponent,net.minecraft.util.text.ITextComponent[]> check=template.validate(inventory);
        if(!Boolean.TRUE.equals(check._1())) throw new IllegalArgumentException("invalid native robot assembly: "+
            (check._2()==null?"CPU, memory or complexity":check._2().getUnformattedText()));
        ItemStack robot=template.assemble(inventory)._1();
        if(robot.isEmpty()) throw new IllegalStateException("native robot assembly returned no robot");
        RobotData data=new RobotData(robot);
        // RobotData serializes copies. Retain the actual selected drive inside that data.
        int driveIndex=-1;
        for(int slot=4,index=0;slot<inventory.getSizeInventory();slot++) if(!inventory.getStackInSlot(slot).isEmpty()) {
            if(inventory.getStackInSlot(slot)==bootDrive) driveIndex=index;
            index++;
        }
        if(driveIndex<0) throw new IllegalStateException("boot drive absent from native assembly");
        return new RunnerHardware(data,data.components()[driveIndex],equipment);
    }
    private static List<ItemStack> parts(JsonObject h,String key,String kind) {
        List<ItemStack> items=new ArrayList<>();
        for(JsonElement name:h.getAsJsonArray(key)) {
            ItemStack stack=configured(name); requireKind(stack,kind); items.add(stack);
        }
        return items;
    }
    private static void requireKind(ItemStack stack,String kind) {
        li.cil.oc.api.driver.DriverItem driver=li.cil.oc.api.Driver.driverFor(stack,Robot.class);
        if(driver==null || !kind.equals(driver.slot(stack))) throw new IllegalArgumentException(
            "hardware "+li.cil.oc.api.Items.get(stack).name()+" is not a robot "+kind);
    }
    private static int[] place(InventoryBasic inventory,AssemblerTemplates.Slot[] slots,int offset,List<ItemStack> items,String label) {
        boolean[][] fits=new boolean[items.size()][slots.length];
        for(int i=0;i<items.size();i++) for(int s=0;s<slots.length;s++) fits[i][s]=slots[s].validate(inventory,offset+s,items.get(i));
        int[] assignment=match(fits,slots.length);
        if(assignment==null) {
            List<String> names=new ArrayList<>();for(ItemStack stack:items) names.add(li.cil.oc.api.Items.get(stack).name());
            throw new IllegalArgumentException("hardware "+label+" do not fit native assembler slots/tier: "+names);
        }
        for(int i=0;i<items.size();i++) inventory.setInventorySlotContents(offset+assignment[i],items.get(i));
        return assignment;
    }
    /** Bounded augmenting matching avoids rejecting a legal mixed-tier recipe due to input order. */
    static int[] match(boolean[][] fits,int slots) {
        int[] occupants=new int[slots]; Arrays.fill(occupants,-1);
        for(int item=0;item<fits.length;item++) if(!assign(item,fits,occupants,new boolean[slots])) return null;
        int[] result=new int[fits.length];
        for(int slot=0;slot<slots;slot++) if(occupants[slot]>=0) result[occupants[slot]]=slot;
        return result;
    }
    private static boolean assign(int item,boolean[][] fits,int[] occupants,boolean[] visited) {
        for(int slot=0;slot<occupants.length;slot++) if(!visited[slot] && fits[item][slot]) {
            visited[slot]=true;
            if(occupants[slot]<0 || assign(occupants[slot],fits,occupants,visited)) {occupants[slot]=item;return true;}
        }
        return false;
    }
    void equip(Robot robot) {
        for(int index=0;index<equipment.size();index++) {
            ItemStack stack=equipment.get(index); if(stack.isEmpty()) continue;
            int slot=index+1;
            if(!robot.isItemValidForSlot(slot,stack)) throw new IllegalArgumentException(
                "hardware container "+(index+1)+" rejects "+li.cil.oc.api.Items.get(stack).name());
            robot.setInventorySlotContents(slot,stack);
        }
    }
}
