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
import net.minecraft.util.EnumFacing;
import net.minecraft.util.SoundCategory;
import net.minecraft.util.SoundEvent;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.EnumSkyBlock;
import net.minecraft.world.IWorldEventListener;
import net.minecraft.world.World;
import net.minecraft.world.WorldServer;

/** The region's cells as observed: the first drain lists every cell that is not air (air is implied), each later one
 *  the cells whose state differs from the last drain. The world reports every block it sets, so a sample costs the
 *  cells that changed, never a scan of the region. ACTUAL reports what a client draws (getActualState: stair
 *  shapes, fence and pane connections), which a change can alter in the six cells round it, so those are checked too.
 *  It also reports the light the world holds (drainLight) over the region grown by LIGHT in x and z, the cells a
 *  change can shade: the first drain every cell whose light differs from what its state implies (none under an
 *  opaque cube, full sky elsewhere), each later one the cells the world relit since. */
final class RegionChanges implements IWorldEventListener, Closeable {
    private static final IBlockState AIR=Blocks.AIR.getDefaultState();
    private final WorldServer world;
    private final int[] min,max;
    private final boolean actual;
    private final Map<BlockPos,IBlockState> seen=new HashMap<>();   // cells last reported as other than air
    private final Set<BlockPos> dirty=new LinkedHashSet<>();
    private boolean scanned;
    static final int LIGHT=15;
    private final Set<BlockPos> lit=new LinkedHashSet<>();
    private byte[] light;                                            // sky<<4|block last reported, over the light box
    RegionChanges(WorldServer world,int[] min,int[] max) {this(world,min,max,false);}
    RegionChanges(WorldServer world,int[] min,int[] max,boolean actual) {
        this.world=world;this.min=min;this.max=max;this.actual=actual;world.addEventListener(this);
    }
    private IBlockState state(BlockPos p) {
        IBlockState state=world.getBlockState(p);
        return actual && state!=AIR?state.getActualState(world,p):state;
    }
    private static int packed(WorldServer world,BlockPos p) {return world.getLightFor(EnumSkyBlock.SKY,p)<<4|world.getLightFor(EnumSkyBlock.BLOCK,p);}
    private int index(BlockPos p) {
        int sx=max[0]-min[0]+1+2*LIGHT,sy=max[1]-min[1]+1;
        return ((p.getZ()-min[2]+LIGHT)*sy+(p.getY()-min[1]))*sx+(p.getX()-min[0]+LIGHT);
    }
    private boolean lightBox(int x,int y,int z) {
        return x>=min[0]-LIGHT && x<=max[0]+LIGHT && y>=min[1] && y<=max[1] && z>=min[2]-LIGHT && z<=max[2]+LIGHT;
    }
    /** Light changes as [x, y, z, sky, block]. */
    JsonArray drainLight() {
        JsonArray changes=new JsonArray();
        if(light==null) {
            light=new byte[(max[0]-min[0]+1+2*LIGHT)*(max[1]-min[1]+1)*(max[2]-min[2]+1+2*LIGHT)];lit.clear();
            for(int x=min[0]-LIGHT;x<=max[0]+LIGHT;x++) for(int y=min[1];y<=max[1];y++) for(int z=min[2]-LIGHT;z<=max[2]+LIGHT;z++) {
                BlockPos p=new BlockPos(x,y,z);int v=packed(world,p);light[index(p)]=(byte)v;
                if(v!=(world.getBlockState(p).isOpaqueCube()?0:15<<4)) changes.add(lightCell(p,v));
            }
            return changes;
        }
        for(BlockPos p:lit) {int v=packed(world,p),i=index(p);if((light[i]&255)!=v) {light[i]=(byte)v;changes.add(lightCell(p,v));}}
        lit.clear();
        return changes;
    }
    private static JsonArray lightCell(BlockPos p,int v) {JsonArray a=RunnerObservations.coords(p);a.add(v>>4);a.add(v&15);return a;}
    JsonArray drain() {
        JsonArray changes=new JsonArray();
        if(!scanned) {
            scanned=true;dirty.clear();
            for(int x=min[0];x<=max[0];x++) for(int y=min[1];y<=max[1];y++) for(int z=min[2];z<=max[2];z++) {
                BlockPos p=new BlockPos(x,y,z);IBlockState state=state(p);
                if(state!=AIR) {seen.put(p,state);changes.add(RunnerObservations.cell(p,state));}
            }
            return changes;
        }
        Set<BlockPos> check=dirty;
        if(actual && !dirty.isEmpty()) {
            check=new LinkedHashSet<>(dirty);
            for(BlockPos p:dirty) for(EnumFacing f:EnumFacing.values()) {BlockPos q=p.offset(f);if(inside(q)) check.add(q);}
        }
        for(BlockPos p:check) {JsonObject c=changed(seen,p,state(p));if(c!=null) changes.add(c);}
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
    @Override public void notifyLightSet(BlockPos pos) {
        if(actual && lightBox(pos.getX(),pos.getY(),pos.getZ())) lit.add(pos.toImmutable());
    }
    /** Chunk.relightBlock sets sky light down a column without notifyLightSet, then marks the column for render. */
    @Override public void markBlockRangeForRenderUpdate(int x1,int y1,int z1,int x2,int y2,int z2) {
        if(!actual) return;
        for(int x=Math.max(x1,min[0]-LIGHT);x<=Math.min(x2,max[0]+LIGHT);x++) for(int y=Math.max(y1,min[1]);y<=Math.min(y2,max[1]);y++)
            for(int z=Math.max(z1,min[2]-LIGHT);z<=Math.min(z2,max[2]+LIGHT);z++) lit.add(new BlockPos(x,y,z));
    }
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
