package ocelot.spike;

import com.google.gson.*;
import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import li.cil.oc.api.machine.Machine;
import li.cil.repack.com.naef.jnlua.LuaState;

/** Opt-in host heap census of scenario controllers (-Drobotspike.heapCensusFile=ndjson path). It runs on the
 *  worker thread right after one of the machine's slices, under the machine lock OC's own save takes, so the
 *  controller's Lua is frozen while heap_census.lua reads it. OC programs never see it. A census is taken at the
 *  first slice, at each new low of free memory LOW_STEP below the last, and every heapCensusEverySeconds. */
final class RunnerHeapCensus {
    static final int LOW_STEP=64*1024, LOW_SPACING_TICKS=20, CENSUS_LIMIT=256;
    private static final long FILE_LIMIT=32L*1024*1024;
    private static final Map<Object,Watched> watched=Collections.synchronizedMap(new IdentityHashMap<>());
    private static String chunk;
    private static BufferedWriter writer;
    private static long bytes;
    private static int censuses;
    private RunnerHeapCensus() {}

    static void watch(Machine machine,String label) {
        if(System.getProperty("robotspike.heapCensusFile")!=null) watched.put(machine,new Watched(machine,label));
    }
    /** Scheduler hook: the worker thread, once a machine's slice has returned. */
    static void afterSlice(Object task) {
        Watched w=watched.isEmpty()?null:watched.get(task);
        if(w!=null) try {w.afterSlice();} catch(Exception|LinkageError e) {w.fail(e);}
    }
    static String reason(long tick,long lastTick,long everyTicks,int free,int lowest) {
        if(lastTick<0) return "first";
        if(free<=lowest-LOW_STEP && tick-lastTick>=LOW_SPACING_TICKS) return "low";
        return tick-lastTick>=everyTicks?"every":null;
    }
    static synchronized String chunk() throws IOException {
        if(chunk==null) try(InputStream in=RunnerHeapCensus.class.getResourceAsStream("/heap_census.lua")) {
            if(in==null) throw new IOException("heap_census.lua absent");
            ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int n;
            while((n=in.read(buffer))!=-1) out.write(buffer,0,n);
            chunk=new String(out.toByteArray(),StandardCharsets.UTF_8);
        }
        return chunk;
    }
    private static synchronized void write(JsonObject row) throws IOException {
        if(censuses>=CENSUS_LIMIT || bytes>=FILE_LIMIT) return;
        if(writer==null) writer=Files.newBufferedWriter(Paths.get(System.getProperty("robotspike.heapCensusFile")),StandardCharsets.UTF_8,
            StandardOpenOption.CREATE,StandardOpenOption.TRUNCATE_EXISTING,StandardOpenOption.WRITE);
        String line=row.toString();writer.write(line);writer.newLine();writer.flush();
        bytes+=line.length()+1;censuses++;
    }

    private static final class Watched {
        private final Machine machine;
        private final String label;
        private final long everyTicks=20L*Long.getLong("robotspike.heapCensusEverySeconds",60L);
        private Field state;
        private Method architecture,lua,kernelMemory,ramScale;
        private long lastTick=-1;
        private int lowest=Integer.MAX_VALUE;
        private boolean failed;
        Watched(Machine machine,String label) {this.machine=machine;this.label=label;}

        void afterSlice() throws Exception {
            if(failed) return;
            if(architecture==null) {
                architecture=machine.getClass().getMethod("architecture");
                state=machine.getClass().getDeclaredField("state");state.setAccessible(true);
            }
            Object arch=architecture.invoke(machine);
            if(lua==null || lua.getDeclaringClass()!=arch.getClass()) {
                lua=arch.getClass().getMethod("lua");kernelMemory=arch.getClass().getMethod("kernelMemory");
                ramScale=arch.getClass().getMethod("ramScale");
            }
            Object raw=lua.invoke(arch);
            if(!(raw instanceof LuaState)) return; // LuaJ machines have no native heap to read.
            LuaState heap=(LuaState)raw;
            int kernel=((Number)kernelMemory.invoke(arch)).intValue();
            if(kernel<=0) return; // Not past OC's initialization run.
            double scale=((Number)ramScale.invoke(arch)).doubleValue();
            int limit=heap.getTotalMemory();
            int free=(int)(Math.min(heap.getFreeMemory(),limit-kernel)/scale);
            long tick=Trace.tick;
            String reason=reason(tick,lastTick,everyTicks,free,lowest);
            if(reason==null) return;
            synchronized(machine) {
                if(!idle()) return; // A synchronized call is pending; a later slice retries.
                synchronized(heap) {
                    if(heap.getTop()!=1 || !heap.isThread(1)) return;
                    census(heap,reason,tick,limit,kernel,scale,free);
                }
            }
        }
        private boolean idle() throws Exception {
            Object stack=state.get(machine);
            String top;synchronized(stack) {top=String.valueOf(stack.getClass().getMethod("top").invoke(stack));}
            return top.equals("Yielded") || top.equals("Sleeping");
        }
        private void census(LuaState lua,String reason,long tick,int limit,int kernel,double scale,int free) throws IOException {
            long started=System.nanoTime();
            JsonObject row=new JsonObject();row.addProperty("kind","heapCensus");row.addProperty("machine",label);
            row.addProperty("reason",reason);row.addProperty("tick",tick);row.addProperty("gameSeconds",tick/20.0);
            row.addProperty("totalBytes",(int)((limit-kernel)/scale));row.addProperty("freeBytes",free);
            row.addProperty("kernelBaselineBytes",(int)(kernel/scale));
            lua.setTotalMemory(Integer.MAX_VALUE);
            try {
                int before=lua.getTotalMemory()-lua.getFreeMemory();
                lua.gc(LuaState.GcAction.COLLECT,0);
                int after=lua.getTotalMemory()-lua.getFreeMemory();
                // usedBytes is what computer.freeMemory() leaves after a full collection; heapBytes adds
                // OC's kernel baseline, which is the total the census walk accounts for.
                row.addProperty("usedBytes",(int)((after-kernel)/scale));row.addProperty("heapBytes",(int)(after/scale));
                row.addProperty("garbageBytes",(int)((before-after)/scale));
                lua.load(chunk(),"=heapcensus");lua.pushValue(1);lua.pushNumber(scale);lua.call(2,1);
                row.add("census",new JsonParser().parse(lua.toString(-1)));
            } catch(RuntimeException error) {
                row.addProperty("error",String.valueOf(error.getMessage()));
            } finally {
                lua.setTop(1);lua.gc(LuaState.GcAction.COLLECT,0);lua.setTotalMemory(limit);
            }
            row.addProperty("wallMillis",(System.nanoTime()-started)/1e6);
            lastTick=tick;lowest=Math.min(lowest,free);
            write(row);
        }
        void fail(Throwable error) {
            failed=true;
            JsonObject row=new JsonObject();row.addProperty("kind","heapCensus");row.addProperty("machine",label);
            row.addProperty("tick",Trace.tick);row.addProperty("error",error.toString());
            try {write(row);} catch(IOException ignored) {}
        }
    }
}
