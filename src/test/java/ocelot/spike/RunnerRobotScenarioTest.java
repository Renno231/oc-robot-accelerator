package ocelot.spike;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class RunnerRobotScenarioTest {
    @Test public void coordinatorMayFinishWithHealthyPersistentRobotServices() {
        assertTrue(RunnerDrones.completionReady(true,true,true,false,false));
        assertFalse(RunnerDrones.completionReady(true,false,true,true,true));
        assertFalse(RunnerDrones.completionReady(true,true,false,true,true));
        assertFalse(RunnerDrones.completionReady(false,false,false,true,false));
        assertFalse(RunnerDrones.completionReady(false,false,false,false,true));
        assertTrue(RunnerDrones.completionReady(false,false,false,true,true));
    }
    private JsonObject fixture() throws Exception {
        JsonObject root=new JsonParser().parse(new String(Files.readAllBytes(Paths.get("fixtures/runner-hardware-normalized.json")),StandardCharsets.UTF_8)).getAsJsonObject();
        JsonObject robot=root.getAsJsonObject("robot");robot.remove("tool");robot.remove("randomSeed");
        JsonObject program=root.getAsJsonObject("program");program.addProperty("directory","robot-program-0");robot.add("program",program);
        JsonArray robots=new JsonArray();robots.add(robot);root.add("robots",robots);root.remove("robot");root.remove("program");
        root.addProperty("schemaVersion",4);root.getAsJsonObject("execution").addProperty("mode","coordinated");
        root.getAsJsonObject("execution").addProperty("infiniteEnergy",true);
        root.add("drones",new JsonArray());
        root.add("containers",new JsonParser().parse("[{\"position\":[0,65,0],\"block\":\"minecraft:chest\",\"slots\":[]}]"));
        root.add("expect",new JsonParser().parse("{\"blocks\":[],\"containers\":[],\"drones\":[],\"robots\":[{\"index\":0}]}"));
        root.add("containerEdits",new JsonParser().parse("[{\"position\":[0,65,0],\"slot\":1,\"count\":2,\"expectedCount\":4,\"atTick\":3}]"));
        return root;
    }
    private void rejects(JsonObject root) {
        try {RunnerScenario.parse(root.toString());fail("accepted invalid robot scenario");}
        catch(IllegalArgumentException expected) {}
    }
    @Test public void robotsOnlyAndExplicitInfiniteEnergy() throws Exception {
        RunnerScenario spec=RunnerScenario.parse(fixture().toString());assertEquals(1,spec.v4.robots.size());assertTrue(spec.v4.infiniteEnergy);assertEquals(1,spec.v4.containerEdits.size());
        JsonObject root=fixture();root.getAsJsonObject("execution").remove("infiniteEnergy");assertFalse(RunnerScenario.parse(root.toString()).v4.infiniteEnergy);
        root.getAsJsonObject("execution").addProperty("infiniteEnergy","true");rejects(root);
    }
    @Test public void strictRobotContract() throws Exception {
        for(String key:new String[]{"facing","energy","hardware","program","inventory"}) {
            JsonObject root=fixture();root.getAsJsonArray("robots").get(0).getAsJsonObject().remove(key);rejects(root);
        }
        JsonObject root=fixture();root.add("robots",new JsonArray());rejects(root);
        root=fixture();root.getAsJsonArray("robots").get(0).getAsJsonObject().getAsJsonObject("program").addProperty("directory","program");rejects(root);
        root=fixture();root.getAsJsonArray("robots").get(0).getAsJsonObject().addProperty("facing","up");rejects(root);
        root=fixture();root.getAsJsonObject("expect").getAsJsonArray("robots").get(0).getAsJsonObject().addProperty("index",1);rejects(root);
        root=fixture();root.getAsJsonObject("expect").getAsJsonArray("robots").get(0).getAsJsonObject().add("inventory",new JsonParser().parse("[{\"slot\":85,\"count\":0}]"));
        assertEquals(1,RunnerScenario.parse(root.toString()).v4.robots.size());
        root.getAsJsonObject("expect").getAsJsonArray("robots").get(0).getAsJsonObject().add("inventory",new JsonParser().parse("[{\"slot\":86,\"count\":0}]"));rejects(root);
    }
    @Test public void assemblyConsumesDeclaredPartsAfterAnExplicitPlayerTrigger() throws Exception {
        JsonObject root=fixture();
        root.add("computer",new JsonParser().parse("{\"position\":[-1,65,0],\"hardware\":{\"tier\":3,\"cpu\":\"cpu3\",\"memory\":[\"ram6\"],\"cards\":[\"wlancard2\"],\"storage\":[\"hdd3\"],\"bootDrive\":0},\"program\":{\"directory\":\"program\",\"entry\":\"main.lua\"}}"));
        JsonArray robots=root.getAsJsonArray("robots");
        JsonObject added=new JsonParser().parse(robots.get(0).toString()).getAsJsonObject();
        added.add("position",new JsonParser().parse("[1,65,0]"));
        added.getAsJsonObject("program").addProperty("directory","robot-program-1");
        added.add("assembly",new JsonParser().parse("{\"source\":[0,65,0],\"blocks\":[],\"request\":{\"computer\":0,\"marker\":\"home/assemble\",\"signal\":\"assembled\"}}"));
        robots.add(added);assertEquals(2,RunnerScenario.parse(root.toString()).v4.robots.size());
        for(String fault:new String[]{"source","marker","controller","energy","unknown","first"}) {
            JsonObject bad=new JsonParser().parse(root.toString()).getAsJsonObject();
            JsonObject a=bad.getAsJsonArray("robots").get(1).getAsJsonObject().getAsJsonObject("assembly");
            if(fault.equals("source")) a.add("source",new JsonParser().parse("[2,65,0]"));
            else if(fault.equals("marker")) a.getAsJsonObject("request").addProperty("marker","../outside");
            else if(fault.equals("controller")) a.getAsJsonObject("request").addProperty("computer",1);
            else if(fault.equals("energy")) a.getAsJsonArray("blocks").add(new JsonParser().parse("{\"position\":[2,65,0],\"block\":\"minecraft:chest\",\"properties\":{},\"energy\":100}"));
            else if(fault.equals("unknown")) a.addProperty("ignoreMissing",true);
            else bad.getAsJsonArray("robots").get(0).getAsJsonObject().add("assembly",a);
            rejects(bad);
        }
    }
    @Test public void strictContainerEditTriggerAndCapacity() throws Exception {
        for(String key:new String[]{"atTick","position","count","slot"}) {
            JsonObject root=fixture();root.getAsJsonArray("containerEdits").get(0).getAsJsonObject().remove(key);rejects(root);
        }
        JsonObject root=fixture();root.getAsJsonArray("containerEdits").get(0).getAsJsonObject().addProperty("expectedCount",1);rejects(root);
        root=fixture();root.getAsJsonArray("containerEdits").get(0).getAsJsonObject().add("request",new JsonParser().parse("{\"computer\":0,\"marker\":\"home/a\",\"signal\":\"done\"}"));rejects(root);
        root=fixture();JsonObject edit=root.getAsJsonArray("containerEdits").get(0).getAsJsonObject();edit.remove("atTick");edit.add("request",new JsonParser().parse("{\"computer\":0,\"marker\":\"home/a\",\"signal\":\"done\"}"));rejects(root);
    }
    @Test public void containerBound128() throws Exception {
        JsonObject root=fixture();root.add("containerEdits",new JsonArray());
        root.getAsJsonObject("world").getAsJsonObject("region").add("max",new JsonParser().parse("[127,67,2]"));
        root.getAsJsonObject("world").add("blocks",new JsonArray());
        JsonArray containers=new JsonArray(),expected=new JsonArray();
        for(int x=0;x<128;x++) {
            JsonObject c=new JsonObject();c.add("position",new JsonParser().parse("["+x+",65,0]"));c.addProperty("block","minecraft:chest");c.add("slots",new JsonArray());containers.add(c);
            JsonObject e=new JsonObject();e.add("position",c.get("position"));e.add("slots",new JsonArray());expected.add(e);
        }
        root.add("containers",containers);root.getAsJsonObject("expect").add("containers",expected);
        assertEquals(128,RunnerScenario.parse(root.toString()).v4.containers.size());
        containers.add(containers.get(0));rejects(root);containers.remove(128);
        expected.add(expected.get(0));rejects(root);
    }
}
