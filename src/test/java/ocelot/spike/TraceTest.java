package ocelot.spike;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class TraceTest {
    private static final class Probe {
        private final Object state = "Stack(Paused, SynchronizedReturn)";
        private final int remainingPause = 1, remainIdle = 0;
        private final long uptime = 897, worldTime = 900;
    }

    @Test public void diagnosticWindowsAreFiniteAroundStartupAndSaves() {
        for (long tick : new long[]{1, 110, 890, 900, 910, 1790, 1800, 1810}) assertTrue(Trace.schedulerWindow(tick));
        for (long tick : new long[]{0, 111, 500, 889, 911, 1789, 1811}) assertFalse(Trace.schedulerWindow(tick));
    }

    @Test public void recordsSchedulerStateOnlyInsideWindows() throws Exception {
        Path root = Files.createTempDirectory("robot-trace-test-");
        try {
            Trace.open(root, true);
            Trace.tick = 500; Trace.machine(new Probe(), "save:return");
            Trace.tick = 900; Trace.machine(new Probe(), "save:return");
            Trace.close();
            String text = new String(Files.readAllBytes(root.resolve("trace.ndjson")), StandardCharsets.UTF_8);
            assertEquals(1, text.trim().split("\\r?\\n").length);
            assertTrue(text.contains("\"remainingPause\":1"));
            assertTrue(text.contains("\"sampleTick\":900"));
            assertTrue(text.contains("Stack(Paused, SynchronizedReturn)"));
        } finally { Trace.close(); Files.deleteIfExists(root.resolve("trace.ndjson")); Files.delete(root); }
    }

    @Test public void gateActionCounterWorksEvenWithTraceDisabled() throws Exception {
        Path root = Files.createTempDirectory("robot-trace-test-");
        try {
            Trace.open(root, false);
            Trace.callback(new Object[]{true}, "move", new Object[]{3});
            Trace.callback(new Object[]{true}, "setData", new Object[]{"READY"});
            assertEquals(1, Trace.actionCount());
            assertEquals(0, Trace.actionSpanNanos());
            assertFalse(Files.exists(root.resolve("trace.ndjson")));
        } finally { Trace.close(); Files.delete(root); }
    }
}
