package ocelot.spike;

import com.google.gson.JsonObject;

/** Gates the native server's periodic save branch; final/explicit saves stay native. */
public final class RunnerAutosave {
    private static long intervalNanos, lastNanos, periodicSaves;
    static void configure(int seconds) { configureAt(seconds,System.nanoTime()); }
    static void configureAt(int seconds,long now) {
        if(seconds<0)throw new IllegalArgumentException("negative autosave interval");
        intervalNanos=seconds*1000000000L;lastNanos=now;periodicSaves=0;
    }
    public static int remainder(int tick) { return remainderAt(tick,System.nanoTime()); }
    static int remainderAt(int tick,long now) {
        if(intervalNanos==0) {
            int remainder=tick%900;
            if(remainder==0)periodicSaves++;
            return remainder;
        }
        if(now-lastNanos<intervalNanos)return 1;
        lastNanos=now;periodicSaves++;return 0;
    }
    static JsonObject report() {
        JsonObject result=new JsonObject();
        result.addProperty("clock",intervalNanos==0?"native_ticks":"wall_clock");
        result.addProperty("wallSeconds",intervalNanos/1000000000L);
        result.addProperty("periodicSaveBranches",periodicSaves);
        result.addProperty("finalAndExplicitSaves","native");
        return result;
    }
}
