package ocelot.spike;

import org.junit.Test;
import static org.junit.Assert.*;

public class RunnerHardwareTest {
    @Test public void mixedTierMatchingDoesNotDependOnGreedyInputOrder() {
        assertArrayEquals(new int[]{1,0},RunnerHardware.match(new boolean[][]{{true,true},{true,false}},2));
        assertArrayEquals(new int[]{0,1},RunnerHardware.match(new boolean[][]{{true,false},{true,true}},2));
        assertArrayEquals(new int[]{2,1,0},RunnerHardware.match(new boolean[][]{{true,true,true},{true,true,false},{true,false,false}},3));
    }
    @Test public void impossibleAndEmptyLoadouts() {
        assertNull(RunnerHardware.match(new boolean[][]{{true,false},{true,false}},2));
        assertNull(RunnerHardware.match(new boolean[][]{{false,false}},2));
        assertArrayEquals(new int[0],RunnerHardware.match(new boolean[0][0],3));
    }
}
