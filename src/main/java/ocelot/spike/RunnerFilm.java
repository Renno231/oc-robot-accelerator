package ocelot.spike;

import com.google.gson.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import li.cil.oc.common.entity.Drone;
import net.minecraft.block.BlockSlab;
import net.minecraft.block.state.IBlockState;
import net.minecraft.util.EnumFacing;
import net.minecraft.util.math.AxisAlignedBB;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.WorldServer;

/** observations.film: the per-tick film track an offline renderer replays (film.ndjson). One line per world tick
 *  in which something a camera sees changed: the first lists the region's cells other than air (as a client draws
 *  them, getActualState) and every drone, later ones only the cells, drones and containers that changed.
 *  A drone is [index, x, y, z] when only it moved, [index, x, y, z, running, lightColor] when either changed.
 *  "light" lists the cells the world relit as [x, y, z, sky, block] (RegionChanges.drainLight) and "states"
 *  describes each block state the first time a line names it, with the server's answers a client mesher needs. */
final class RunnerFilm implements Closeable {
    private final RunnerScenario spec;
    private final WorldServer world;
    private final RegionChanges region;
    private final Writer out;
    private double[][] last;
    private boolean[] running;
    private int[] light;
    private String containers;
    private final Set<String> described=new HashSet<>();
    RunnerFilm(RunnerScenario spec,WorldServer world,Path root) throws IOException {
        this.spec=spec;this.world=world;
        region=new RegionChanges(world,spec.min,spec.max,true);
        out=new BufferedWriter(new OutputStreamWriter(Files.newOutputStream(root.resolve("film.ndjson"),StandardOpenOption.CREATE_NEW),"UTF-8"),1<<16);
    }
    private static double round(double v) {return Math.round(v*1000)/1000.0;}
    void tick(long tick,List<Drone> drones) throws IOException {
        boolean first=last==null;
        if(first) {last=new double[drones.size()][];running=new boolean[drones.size()];light=new int[drones.size()];}
        JsonObject line=new JsonObject();line.addProperty("tick",tick);
        if(first) {
            line.addProperty("film",1);JsonObject bounds=new JsonObject();
            bounds.add("min",RunnerObservations.coords(RunnerObservations.pos(spec.min)));bounds.add("max",RunnerObservations.coords(RunnerObservations.pos(spec.max)));
            line.add("region",bounds);
        }
        JsonArray blocks=region.drain();
        if(first || blocks.size()>0) line.add("blocks",blocks);
        JsonArray states=new JsonArray();
        for(JsonElement e:blocks) {
            JsonObject cell=e.getAsJsonObject();String key=cell.get("block")+""+cell.get("properties");
            if(!described.add(key)) continue;
            JsonArray at=cell.getAsJsonArray("position");
            BlockPos p=new BlockPos(at.get(0).getAsInt(),at.get(1).getAsInt(),at.get(2).getAsInt());
            states.add(describe(cell,p,world.getBlockState(p).getActualState(world,p)));
        }
        if(states.size()>0) line.add("states",states);
        JsonArray lit=region.drainLight();
        if(first || lit.size()>0) line.add("light",lit);
        JsonArray moved=new JsonArray();
        for(int i=0;i<drones.size();i++) {
            Drone d=drones.get(i);double[] p={round(d.posX),round(d.posY),round(d.posZ)};
            boolean on=d.isRunning();int color=d.lightColor();
            boolean look=first || on!=running[i] || color!=light[i];
            if(!look && Arrays.equals(p,last[i])) continue;
            JsonArray e=new JsonArray();e.add(i);for(double v:p) e.add(v);
            if(look) {e.add(on);e.add(color);}
            moved.add(e);last[i]=p;running[i]=on;light[i]=color;
        }
        if(moved.size()>0) line.add("drones",moved);
        JsonArray stock=RunnerContainers.result(spec,world);String text=stock.toString();
        if(!text.equals(containers)) {line.add("containers",stock);containers=text;}
        if(line.size()>1) {out.write(line.toString());out.write('\n');}
    }
    /** What the client mesher asks a state: culling (opaque, sides it hides, box), light (opacity, emission,
     *  neighbour brightness, slab), ambient occlusion (normal cube). */
    private JsonObject describe(JsonObject cell,BlockPos p,IBlockState s) {
        JsonObject d=new JsonObject();d.add("block",cell.get("block"));d.add("properties",cell.get("properties"));
        d.addProperty("opaque",s.isOpaqueCube());d.addProperty("full",s.isFullCube());d.addProperty("normal",s.isBlockNormalCube());
        d.addProperty("opacity",s.getLightOpacity(world,p));d.addProperty("light",s.getLightValue(world,p));
        d.addProperty("nbright",s.useNeighborBrightness());d.addProperty("slab",s.getBlock() instanceof BlockSlab);
        int hides=0;for(EnumFacing f:EnumFacing.values()) if(s.doesSideBlockRendering(world,p,f)) hides|=1<<f.ordinal();
        d.addProperty("hides",hides);
        AxisAlignedBB b=s.getBoundingBox(world,p);JsonArray box=new JsonArray();
        for(double v:new double[]{b.minX,b.minY,b.minZ,b.maxX,b.maxY,b.maxZ}) box.add(v);
        d.add("box",box);return d;
    }
    @Override public void close() throws IOException {region.close();out.close();}
}
