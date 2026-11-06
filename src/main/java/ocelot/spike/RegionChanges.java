package ocelot.spike;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.io.Closeable;
import java.util.*;
import javax.annotation.Nullable;
import net.minecraft.block.state.IBlockState;
import net.minecraft.entity.Entity;
import net.minecraft.entity.player.EntityPlayer;
import net.minecraft.init.Blocks;
import net.minecraft.util.SoundCategory;
import net.minecraft.util.SoundEvent;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.IWorldEventListener;
import net.minecraft.world.World;
import net.minecraft.world.WorldServer;

/** The region's cells as observed: the first drain lists every cell that is not air (air is implied), each later one
 *  the cells whose state differs from the last drain. The world reports every block it sets, so a sample costs the
 *  cells that changed, never a scan of the region. */
final class RegionChanges implements IWorldEventListener, Closeable {
    private static final IBlockState AIR=Blocks.AIR.getDefaultState();
    private final WorldServer world;
    private final int[] min,max;
    private final Map<BlockPos,IBlockState> seen=new HashMap<>();   // cells last reported as other than air
    private final Set<BlockPos> dirty=new LinkedHashSet<>();
    private boolean scanned;
    RegionChanges(WorldServer world,int[] min,int[] max) {this.world=world;this.min=min;this.max=max;world.addEventListener(this);}
    JsonArray drain() {
        JsonArray changes=new JsonArray();
        if(!scanned) {
            scanned=true;dirty.clear();
            for(int x=min[0];x<=max[0];x++) for(int y=min[1];y<=max[1];y++) for(int z=min[2];z<=max[2];z++) {
                BlockPos p=new BlockPos(x,y,z);IBlockState state=world.getBlockState(p);
                if(state!=AIR) {seen.put(p,state);changes.add(RunnerObservations.cell(p,state));}
            }
            return changes;
        }
        for(BlockPos p:dirty) {JsonObject c=changed(seen,p,world.getBlockState(p));if(c!=null) changes.add(c);}
        dirty.clear();
        return changes;
    }
    /** The cell's record if STATE differs from the one SEEN holds for it (none is air), and SEEN updated. */
    static JsonObject changed(Map<BlockPos,IBlockState> seen,BlockPos p,IBlockState state) {
        IBlockState was=state==AIR?seen.remove(p):seen.put(p,state);
        return state.equals(was==null?AIR:was)?null:RunnerObservations.cell(p,state);
    }
    private boolean inside(BlockPos p) {
        return p.getX()>=min[0] && p.getX()<=max[0] && p.getY()>=min[1] && p.getY()<=max[1] && p.getZ()>=min[2] && p.getZ()<=max[2];
    }
    @Override public void notifyBlockUpdate(World w,BlockPos pos,IBlockState oldState,IBlockState newState,int flags) {
        if(w==world && inside(pos)) dirty.add(pos.toImmutable());
    }
    @Override public void close() {world.removeEventListener(this);}
    @Override public void notifyLightSet(BlockPos pos) {}
    @Override public void markBlockRangeForRenderUpdate(int x1,int y1,int z1,int x2,int y2,int z2) {}
    @Override public void playSoundToAllNearExcept(@Nullable EntityPlayer player,SoundEvent sound,SoundCategory category,double x,double y,double z,float volume,float pitch) {}
    @Override public void playRecord(SoundEvent sound,BlockPos pos) {}
    @Override public void spawnParticle(int id,boolean ignoreRange,double x,double y,double z,double dx,double dy,double dz,int... parameters) {}
    @Override public void spawnParticle(int id,boolean ignoreRange,boolean minimise,double x,double y,double z,double dx,double dy,double dz,int... parameters) {}
    @Override public void onEntityAdded(Entity entity) {}
    @Override public void onEntityRemoved(Entity entity) {}
    @Override public void broadcastSound(int id,BlockPos pos,int data) {}
    @Override public void playEvent(EntityPlayer player,int type,BlockPos pos,int data) {}
    @Override public void sendBlockBreakProgress(int breakerId,BlockPos pos,int progress) {}
}
