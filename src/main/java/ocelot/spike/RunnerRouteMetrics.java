package ocelot.spike;

import com.google.gson.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.List;
import li.cil.oc.common.entity.Drone;
import net.minecraft.util.math.Vec3d;

/** Opt-in compact per-tick native measurements, independent of replay coverage.
 * Enabled by a frozen program marker; no callbacks or world updates are added. */
final class RunnerRouteMetrics implements Closeable {
    private final BufferedWriter writer;
    private long bytes;
    RunnerRouteMetrics(Path root) throws IOException {
        writer=Files.newBufferedWriter(root.resolve("route-observations.ndjson"),StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW);
    }
    private static JsonArray vector(Vec3d p) {JsonArray v=new JsonArray();v.add(p.x);v.add(p.y);v.add(p.z);return v;}
    void sample(long tick,List<Drone> drones) throws IOException {
        JsonObject record=new JsonObject();record.addProperty("tick",tick);record.addProperty("wallNanos",System.nanoTime());
        JsonArray all=new JsonArray();
        for(int i=0;i<drones.size();i++) {
            Drone d=drones.get(i);JsonObject value=new JsonObject();value.addProperty("index",i);
            value.addProperty("uptime",d.machine().upTime());value.addProperty("energyConsumed",RunnerEnergyMetrics.consumed(d.machine()));
            value.add("position",vector(new Vec3d(d.posX,d.posY,d.posZ)));value.add("target",vector(d.getTarget()));value.add("velocity",vector(d.getVelocity().scale(20)));
            all.add(value);
        }
        record.add("drones",all);String line=record.toString()+"\n";
        bytes+=line.getBytes(StandardCharsets.UTF_8).length;
        if(bytes>32L*1024*1024) throw new IOException("route_measurement_limit");
        writer.write(line);
    }
    @Override public void close() throws IOException {writer.close();}
}
