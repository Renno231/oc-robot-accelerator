package ocelot.spike;

import com.google.gson.*;
import java.util.*;
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
            public void power(int index,boolean on) {fail("move only");}
            public void signal(int index,String name) {assertEquals(1,moves);assertEquals("drone_home",name);signals++;}
        }
        World world=new World();action.tick(world);assertEquals(0,world.moves);
        world.requested=true;action.tick(world);action.tick(world);
        assertEquals(1,world.moves);assertEquals(1,world.signals);
    }
    @Test public void stopAndStartPowerTheirDroneOnItsOwnMarker() {
        JsonArray actions=new JsonParser().parse("[{\"action\":\"stop_drone\",\"drone\":1,\"request\":{\"computer\":0,\"marker\":\"home/stop\",\"signal\":\"stopped\"}},"+
            "{\"action\":\"start_drone\",\"drone\":3,\"request\":{\"computer\":0,\"marker\":\"home/start\",\"signal\":\"started\"}}]").getAsJsonArray();
        RunnerDroneActions action=new RunnerDroneActions(actions);
        List<String> log=new ArrayList<>();
        Set<String> markers=new HashSet<>();
        RunnerDroneActions.Environment world=new RunnerDroneActions.Environment() {
            public boolean requested(int index,String marker) {return markers.contains(marker);}
            public void move(int index,double x,double y,double z) {fail("power only");}
            public void power(int index,boolean on) {log.add(index+(on?" on":" off"));}
            public void signal(int index,String name) {log.add(name);}
        };
        markers.add("home/stop");action.tick(world);action.tick(world);
        markers.add("home/start");action.tick(world);
        assertEquals(Arrays.asList("1 off","stopped","3 on","started"),log);
    }
}
