package ocelot.spike;
import org.junit.Test;
import static org.junit.Assert.*;

public class RunnerOutcomePollTest {
    @Test public void firstAndStoppedAreAlwaysInspected() {
        RunnerOutcomePoll poll=new RunnerOutcomePoll();
        assertTrue(poll.due(0,true));
        assertFalse(poll.due(1,true));
        assertTrue(poll.due(2,false));
        assertTrue(poll.due(3,false));
    }
    @Test public void samplingUsesWallTimeNotSimulatedTicks() {
        RunnerOutcomePoll poll=new RunnerOutcomePoll();
        assertTrue(poll.due(100,true));
        assertFalse(poll.due(100+RunnerOutcomePoll.INTERVAL_NANOS-1,true));
        assertTrue(poll.due(100+RunnerOutcomePoll.INTERVAL_NANOS,true));
    }
}
