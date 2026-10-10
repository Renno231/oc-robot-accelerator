package ocelot.spike;

import com.google.gson.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class RunnerDroneActionsTest {
    @Test public void requestMovesOnlyDeclaredEntityOnceBeforeSignal() {
        JsonArray actions=new JsonParser().parse("[{\"action\":\"move_drone\",\"drone\":2,\"to\":[-2,65,2],\"request\":{\"computer\":0,\"marker\":\"home/carry-home\",\"signal\":\"drone_home\"}}]").getAsJsonArray();
        RunnerDroneActions action=new RunnerDroneActions(actions);
        class World implements RunnerDroneActions.Environment {
            boolean requested;int moves,signals;
            public boolean requested(int index,String marker) {assertEquals(0,index);assertEquals("home/carry-home",marker);return requested;}
            public void move(int index,double x,double y,double z) {assertEquals(2,index);assertArrayEquals(new double[]{-1.5,65.5,2.5},new double[]{x,y,z},0);moves++;}
            public void signal(int index,String name) {assertEquals(1,moves);assertEquals("drone_home",name);signals++;}
        }
        World world=new World();action.tick(world);assertEquals(0,world.moves);
        world.requested=true;action.tick(world);action.tick(world);
        assertEquals(1,world.moves);assertEquals(1,world.signals);
    }
}
