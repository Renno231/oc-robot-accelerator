package ocelot.spike;

import org.junit.Test;
import static org.junit.Assert.*;

/** Decisions at the real fixture's worker/terminal observation boundaries. */
public class RobotSpikeTest {
    @Test public void completionRequiresClosedMachineNotOnlyShutdownRequested() {
        assertFalse(RobotSpike.firmwareFinished("PASS:513", "Stopping"));
        assertFalse(RobotSpike.firmwareFinished("PASS:513", "Running"));
        assertFalse(RobotSpike.firmwareFinished("", "Stopped"));
        assertTrue(RobotSpike.firmwareFinished("PASS:513", "Stopped"));
        assertTrue(RobotSpike.firmwareFinished("FAIL:operation", "Stopped"));
    }

    @Test public void runningWorkerUnderPauseOverlayStillNeedsProgress() {
        assertTrue(RobotSpike.workerNeedsTime("Paused", true));
        assertFalse(RobotSpike.workerNeedsTime("Paused", false));
        assertTrue(RobotSpike.workerNeedsTime("Stopping", true));
        assertFalse(RobotSpike.workerNeedsTime("Stopping", false));
    }

    @Test public void queuedWorkersNeedTimeButTickSideWorkMustNotBeBlocked() {
        assertTrue(RobotSpike.workerNeedsTime("Yielded", false));
        assertTrue(RobotSpike.workerNeedsTime("SynchronizedReturn", false));
        assertTrue(RobotSpike.workerNeedsTime("Running", true));
        assertFalse(RobotSpike.workerNeedsTime("SynchronizedCall", false));
        assertFalse(RobotSpike.workerNeedsTime("Sleeping", false));
        assertFalse(RobotSpike.workerNeedsTime("Stopped", false));
    }
}
