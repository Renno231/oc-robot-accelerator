package ocelot.spike;

import org.junit.Test;
import static org.junit.Assert.*;

public class RunnerHeapCensusTest {
    @Test public void firstNewLowAndPeriodicCensuses() {
        int low=RunnerHeapCensus.LOW_STEP;
        assertEquals("first",RunnerHeapCensus.reason(5,-1,1200,900000,Integer.MAX_VALUE));
        assertNull(RunnerHeapCensus.reason(100,5,1200,900000-low+1,900000));
        assertEquals("low",RunnerHeapCensus.reason(100,5,1200,900000-low,900000));
        // A falling slope takes at most one low census per second.
        assertNull(RunnerHeapCensus.reason(24,5,1200,0,900000));
        assertEquals("every",RunnerHeapCensus.reason(1205,5,1200,900000,900000));
    }
    @Test public void censusChunkShipsInTheJar() throws Exception {
        assertTrue(RunnerHeapCensus.chunk().contains("{\"booted\":false}"));
    }
}
