package ocelot.spike;

import com.mojang.authlib.GameProfile;
import java.util.UUID;
import net.minecraft.block.Block;
import net.minecraft.inventory.IInventory;
import net.minecraft.item.ItemStack;
import net.minecraft.tileentity.TileEntity;
import net.minecraft.util.EnumFacing;
import net.minecraft.util.EnumHand;
import net.minecraft.util.EnumActionResult;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.WorldServer;
import net.minecraftforge.common.util.FakePlayer;
import net.minecraftforge.common.util.FakePlayerFactory;

/** Player-equivalent block placement, server insertion and rack GUI side selection. */
final class RunnerRack {
    static TileEntity place(WorldServer world,BlockPos p,int tier) throws Exception {
        FakePlayer owner=FakePlayerFactory.get(world,new GameProfile(UUID.fromString("933cfa95-d269-48dd-8ed0-3c38ef1983fa"),"spike-owner"));
        owner.setPosition(p.getX()+0.5,p.getY(),p.getZ()+0.5);owner.rotationYaw=180;
        placeBlock(world,p,"rack",owner);
        TileEntity rack=world.getTileEntity(p);
        if(rack==null || !rack.getClass().getName().equals("li.cil.oc.common.tileentity.Rack")) throw new IllegalStateException("native rack absent");
        IInventory inventory=(IInventory)rack;
        ItemStack server=RunnerHardware.oc("server"+tier);
        if(!inventory.isItemValidForSlot(0,server)) throw new IllegalArgumentException("native rack rejects server");
        inventory.setInventorySlotContents(0,server);
        rack.getClass().getMethod("connectComponents").invoke(rack);
        if(server(rack)==null || !server(rack).getClass().getName().equals("li.cil.oc.server.component.Server")) throw new IllegalStateException("native rack server absent");
        placeAttachedBlock(world,p,EnumFacing.WEST,"screen3",owner);
        placeAttachedBlock(world,p.west(),EnumFacing.UP,"keyboard",owner);
        // -1 is the mountable's primary node; side coordinates are rack-local.
        EnumFacing side=(EnumFacing)rack.getClass().getMethod("toLocal",EnumFacing.class).invoke(rack,EnumFacing.WEST);
        rack.getClass().getMethod("connect",int.class,int.class,scala.Option.class).invoke(rack,0,-1,scala.Option.apply(side));
        return rack;
    }
    static Object server(TileEntity rack) throws Exception {return rack.getClass().getMethod("getMountable",int.class).invoke(rack,0);}
    private static void placeAttachedBlock(WorldServer world,BlockPos clicked,EnumFacing side,String name,FakePlayer owner) {
        BlockPos p=clicked.offset(side);
        if(!world.isAirBlock(p)) throw new IllegalArgumentException("controller_cell_not_air:"+p);
        ItemStack stack=RunnerHardware.oc(name);owner.setHeldItem(EnumHand.MAIN_HAND,stack);
        // ItemBlock's ordinary placement path sets OC keyboard pitch from the
        // clicked face. A default block state does not mount it to the screen.
        if(stack.onItemUse(owner,world,clicked,EnumHand.MAIN_HAND,side,0.5f,0.5f,0.5f)!=EnumActionResult.SUCCESS)
            throw new IllegalStateException("native peripheral placement rejected:"+name);
        owner.setHeldItem(EnumHand.MAIN_HAND,ItemStack.EMPTY);
    }
    private static void placeBlock(WorldServer world,BlockPos p,String name,FakePlayer owner) {
        if(!world.isAirBlock(p)) throw new IllegalArgumentException("controller_cell_not_air:"+p);
        ItemStack stack=RunnerHardware.oc(name);Block block=Block.getBlockFromItem(stack.getItem());
        world.setBlockState(p,block.getDefaultState(),3);
        block.onBlockPlacedBy(world,p,world.getBlockState(p),owner,stack);
    }
}
