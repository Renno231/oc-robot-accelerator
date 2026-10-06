package ocelot.spike;

import org.junit.Test;
import static org.junit.Assert.*;

public class RunnerDroneErrorsTest {
    @Test public void nativeWakeCannotEraseObservedFailure() {
        assertNull(RunnerDroneErrors.remember(null,null));
        assertEquals("boom",RunnerDroneErrors.remember(null,"boom"));
        assertEquals("boom",RunnerDroneErrors.remember("boom",null));
        assertEquals("boom",RunnerDroneErrors.remember("boom","second"));
    }
}
