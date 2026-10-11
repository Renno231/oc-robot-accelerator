package ocelot.spike;

import com.google.gson.*;
import com.mojang.authlib.GameProfile;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import li.cil.oc.api.machine.Machine;
import li.cil.oc.api.network.Connector;
import li.cil.oc.common.template.AssemblerTemplates;
import li.cil.oc.common.template.AssemblerTemplates$;
import net.minecraft.block.Block;
import net.minecraft.inventory.InventoryBasic;
import net.minecraft.item.ItemStack;
import net.minecraft.tileentity.TileEntity;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.WorldServer;
import net.minecraftforge.common.util.FakePlayer;
import net.minecraftforge.common.util.FakePlayerFactory;

/** Real assembler and block placement; continuous firmware is not a completion gate. */
final class RunnerMicrocontrollers {
    private final JsonObject spec;
    private final WorldServer world;
    private final Path root;
    private TileEntity tile;
    private Machine machine;
    private boolean started;
    RunnerMicrocontrollers(JsonObject spec,WorldServer world,Path root) {this.spec=spec;this.world=world;this.root=root;}
    boolean owns(TileEntity other) {return tile==other;}
    void setup() throws Exception {
        BlockPos position=RunnerContainers.pos(spec);
        if(!world.isAirBlock(position)) throw new IllegalArgumentException("microcontroller_cell_not_air:"+position);
        Path file=root.resolve("eeprom").resolve(RunnerScenario.path(spec.get("eeprom").getAsString()));
        if(Files.size(file)>li.cil.oc.Settings.get().eepromSize()) throw new IllegalArgumentException("microcontroller EEPROM code bound");
        byte[] data=spec.get("eepromData").getAsString().getBytes(StandardCharsets.UTF_8);
        if(data.length>li.cil.oc.Settings.get().eepromDataSize()) throw new IllegalArgumentException("microcontroller EEPROM data bound");
        ItemStack firmware=li.cil.oc.api.Items.registerEEPROM("runner-microcontroller",Files.readAllBytes(file),data,false);
        JsonObject hardware=spec.getAsJsonObject("hardware");
        InventoryBasic inventory=new InventoryBasic("runner microcontroller assembly",false,22);
        ItemStack casing=RunnerHardware.oc("microcontrollercase"+hardware.get("tier").getAsString());
        inventory.setInventorySlotContents(0,casing);
        scala.Option<AssemblerTemplates.Template> selected=AssemblerTemplates$.MODULE$.select(casing);
        if(selected.isEmpty()) throw new IllegalStateException("native microcontroller assembler template absent");
        AssemblerTemplates.Template template=selected.get();
        List<ItemStack> upgrades=new ArrayList<>(),components=new ArrayList<>();
        for(JsonElement part:hardware.getAsJsonArray("upgrades")) upgrades.add(RunnerHardware.oc(part.getAsString()));
        components.add(RunnerHardware.oc(hardware.get("cpu").getAsString()));
        for(String key:new String[]{"memory","cards"}) for(JsonElement part:hardware.getAsJsonArray(key)) components.add(RunnerHardware.oc(part.getAsString()));
        components.add(firmware);
        RunnerHardware.place(inventory,template.upgradeSlots(),4,upgrades,"microcontroller upgrades");
        RunnerHardware.place(inventory,template.componentSlots(),13,components,"microcontroller components");
        scala.Tuple3<Object,net.minecraft.util.text.ITextComponent,net.minecraft.util.text.ITextComponent[]> check=template.validate(inventory);
        if(!Boolean.TRUE.equals(check._1())) throw new IllegalArgumentException("invalid native microcontroller assembly:"+
            (check._2()==null?"CPU, memory or complexity":check._2().getUnformattedText()));
        ItemStack assembled=template.assemble(inventory)._1();
        if(assembled.isEmpty()) throw new IllegalStateException("native microcontroller assembler returned no block");
        Block block=Block.getBlockFromItem(assembled.getItem());
        world.setBlockState(position,block.getDefaultState(),3);
        FakePlayer owner=FakePlayerFactory.get(world,new GameProfile(UUID.fromString("933cfa95-d269-48dd-8ed0-3c38ef1983fa"),"spike-owner"));
        owner.setPosition(position.getX()+0.5,position.getY(),position.getZ()+0.5);owner.rotationYaw=180;
        block.onBlockPlacedBy(world,position,world.getBlockState(position),owner,assembled);
        tile=world.getTileEntity(position);
        if(tile==null || !tile.getClass().getName().equals("li.cil.oc.common.tileentity.Microcontroller")) throw new IllegalStateException("native microcontroller absent");
        machine=(Machine)tile.getClass().getMethod("machine").invoke(tile);
        RunnerScheduler.attachMachine((Runnable)machine);
        tile.getClass().getMethod("connectComponents").invoke(tile);
    }
    boolean prepare(long tick) throws Exception {
        if(started) return true;
        if(tick<3 || machine.node().network()==null) return false;
        Connector power=(Connector)machine.node();
        double energy=spec.has("energy")?spec.get("energy").getAsDouble():power.globalBufferSize();
        if(energy>power.globalBufferSize()) throw new IllegalArgumentException("microcontroller energy exceeds native capacity:"+power.globalBufferSize());
        power.changeBuffer(energy-power.globalBuffer());
        if(!machine.start()) throw new IllegalStateException("microcontroller would not start:"+machine.lastError());
        started=true;return true;
    }
    String tick(boolean infiniteEnergy) {
        if(world.getTileEntity(tile.getPos())!=tile) return "microcontroller_error:removed";
        if(infiniteEnergy) {Connector power=(Connector)machine.node();power.changeBuffer(power.globalBufferSize()-power.globalBuffer());}
        return machine.lastError()==null?null:"microcontroller_error:"+machine.lastError();
    }
    JsonObject snapshot(int index) {
        JsonObject value=new JsonObject();value.addProperty("index",index);value.add("position",RunnerObservations.coords(tile.getPos()));
        value.addProperty("address",machine.node().address());value.addProperty("running",machine.isRunning());
        value.addProperty("lastError",machine.lastError());value.addProperty("energy",((Connector)machine.node()).globalBuffer());
        return value;
    }
    void close() {if(machine!=null) machine.stop();}
}
