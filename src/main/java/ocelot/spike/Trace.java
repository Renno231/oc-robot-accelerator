package ocelot.spike;

import com.google.gson.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/** Bounded observations; callback records never contain generated component identities. */
public final class Trace {
    private static final Set<String> ACTIONS = new HashSet<>(Arrays.asList("move", "swing", "place", "turn", "detect", "drop", "suck", "select"));
    private static BufferedWriter writer;
    private static long bytes, opened, firstAction, lastAction, actions;
    private static volatile boolean enabled;
    public static volatile long tick;
    private Trace() {}
    public static synchronized void open(Path root, boolean enabled) throws IOException {
        if (writer != null) throw new IllegalStateException("Trace already open");
        bytes = 0; opened = System.nanoTime(); firstAction = 0; lastAction = 0; actions = 0;
        if (enabled) writer = Files.newBufferedWriter(root.resolve("trace.ndjson"), StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW);
        Trace.enabled = enabled;
    }
    public static synchronized void record(JsonObject event) {
        if (writer == null) return;
        event.addProperty("tick", tick);
        event.addProperty("elapsedNanos", System.nanoTime() - opened);
        String line = event.toString();
        bytes += line.getBytes(StandardCharsets.UTF_8).length + 1;
        if (bytes > 4 * 1024 * 1024) throw new IllegalStateException("Trace limit");
        try { writer.write(line); writer.newLine(); } catch (IOException e) { throw new UncheckedIOException(e); }
    }
    public static synchronized void callback(Object[] results, String method, Object[] arguments) {
        if (!ACTIONS.contains(method)) return;
        actions++;
        if (writer == null) return;
        lastAction = System.nanoTime();
        if (firstAction == 0) firstAction = lastAction;
        JsonObject event = new JsonObject();
        event.addProperty("kind", "callback"); event.addProperty("method", method);
        event.add("arguments", values(arguments)); event.add("results", values(results));
        record(event);
    }
    /** Narrow diagnostic windows preserve the existing global trace bound. */
    static boolean schedulerWindow(long value) {
        return value > 0 && (value <= 110 || value % 900 <= 10 || value % 900 >= 890);
    }

    public static void machine(Object machine, String boundary) {
        if (!enabled || !schedulerWindow(tick)) return;
        JsonObject event = new JsonObject();
        event.addProperty("kind", "scheduler");
        event.addProperty("boundary", boundary);
        event.addProperty("thread", Thread.currentThread().getName());
        try {
            java.lang.reflect.Field field = machine.getClass().getDeclaredField("state");
            field.setAccessible(true);
            Object stack = field.get(machine);
            // Never hold the trace writer lock while acquiring OC's state lock.
            synchronized (stack) {
                event.addProperty("sampleTick", tick);
                event.addProperty("stateStack", String.valueOf(stack));
                for (String name : new String[]{"remainingPause", "remainIdle", "uptime", "worldTime"}) {
                    field = machine.getClass().getDeclaredField(name);
                    field.setAccessible(true);
                    event.addProperty(name, (Number)field.get(machine));
                }
            }
        } catch (ReflectiveOperationException error) {
            throw new IllegalStateException("Unsupported OC diagnostic fields", error);
        }
        record(event);
    }

    private static JsonElement values(Object[] values) {
        if (values == null) return JsonNull.INSTANCE;
        if (values.length > 16) throw new IllegalStateException("Unexpected callback arity");
        JsonArray array = new JsonArray();
        for (Object value : values) {
            if (value == null || value == scala.runtime.BoxedUnit.UNIT) array.add(JsonNull.INSTANCE);
            else if (value instanceof Boolean) array.add(new JsonPrimitive((Boolean)value));
            else if (value instanceof Number) array.add(new JsonPrimitive((Number)value));
            else {
                String text = value instanceof byte[] ? new String((byte[])value, StandardCharsets.UTF_8) : String.valueOf(value);
                if (text.length() > 256) throw new IllegalStateException("Callback string bound");
                array.add(new JsonPrimitive(text));
            }
        }
        return array;
    }
    public static synchronized long actionSpanNanos() { return lastAction - firstAction; }
    public static synchronized long actionCount() { return actions; }
    public static synchronized void close() throws IOException {
        enabled = false;
        if (writer != null) { try { writer.close(); } finally { writer = null; } }
    }
}
