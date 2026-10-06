package ocelot.spike;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class RunnerDroneScenarioTest {
    private JsonObject fixture() throws Exception {
        JsonObject root=new JsonParser().parse(new String(Files.readAllBytes(Paths.get("fixtures/runner-public-normalized.json")),StandardCharsets.UTF_8)).getAsJsonObject();
        root.addProperty("schemaVersion",4);root.remove("robot");root.remove("program");
        root.getAsJsonObject("execution").addProperty("mode","baseline");
        root.add("containers",new JsonParser().parse("[{\"position\":[0,65,0],\"block\":\"minecraft:chest\",\"slots\":[]}]"));
        root.add("drones",new JsonParser().parse("[{\"position\":[0,65,0],\"hardware\":{\"tier\":2,\"cpu\":\"cpu1\",\"memory\":[\"ram2\"],\"cards\":[],\"upgrades\":[]},\"eeprom\":\"main.lua\",\"eepromData\":\"\",\"inventory\":[]}]"));
        root.add("expect",new JsonParser().parse("{\"blocks\":[],\"containers\":[{\"position\":[0,65,0],\"slots\":[{\"slot\":1,\"count\":0}]}],\"drones\":[{\"index\":0,\"blockPosition\":[0,65,0],\"inventory\":[{\"slot\":1,\"count\":0}]}]}"));
        return root;
    }
    private void rejects(JsonObject value) {
        try {RunnerScenario.parse(value.toString());fail("accepted invalid v4");}
        catch(IllegalArgumentException expected) { }
    }
    @Test public void nativeDroneContract() throws Exception {
        RunnerScenario spec=RunnerScenario.parse(fixture().toString());assertEquals(1,spec.v4.drones.size());assertNull(spec.hardware);assertEquals("baseline",spec.mode);
    }
    @Test public void coordinatedModeAndInvalidMachineCombinations() throws Exception {
        JsonObject accelerated=fixture();accelerated.getAsJsonObject("execution").addProperty("mode","coordinated");assertEquals("coordinated",RunnerScenario.parse(accelerated.toString()).mode);
        JsonObject paced=fixture();paced.getAsJsonObject("execution").addProperty("mode","paced");rejects(paced);
        JsonObject v=fixture();v.add("robot",new JsonObject());rejects(v);
        v=fixture();v.remove("drones");rejects(v);
        v=fixture();v.add("program",new JsonObject());rejects(v);
        v=fixture();v.add("drones",new JsonArray());rejects(v);
    }
    @Test public void strictNativeInputShapes() throws Exception {
        for(String tier:new String[]{"3","true","\"2\"","null"}) {
            JsonObject v=fixture();v.getAsJsonArray("drones").get(0).getAsJsonObject().getAsJsonObject("hardware").add("tier",new JsonParser().parse(tier));rejects(v);
        }
        for(String energy:new String[]{"0","-1","true","\"10\"","1e999"}) {
            JsonObject v=fixture();v.getAsJsonArray("drones").get(0).getAsJsonObject().add("energy",new JsonParser().parse(energy));rejects(v);
        }
        JsonObject v=fixture();v.getAsJsonArray("drones").get(0).getAsJsonObject().addProperty("eeprom","../main.lua");rejects(v);
        v=fixture();v.getAsJsonObject("expect").getAsJsonArray("drones").get(0).getAsJsonObject().addProperty("index",1);rejects(v);
        v=fixture();v.getAsJsonObject("expect").getAsJsonArray("drones").get(0).getAsJsonObject().addProperty("unknown",1);rejects(v);
        v=fixture();v.getAsJsonArray("containers").get(0).getAsJsonObject().add("slots",new JsonParser().parse("[{\"slot\":1,\"item\":\"minecraft:stone\",\"count\":1,\"metadata\":0,\"nbt\":\"{}\"},{\"slot\":1,\"item\":\"minecraft:stone\",\"count\":1,\"metadata\":0,\"nbt\":\"{}\"}]"));rejects(v);
    }
    @Test public void v4RobotRetainsV3Contract() throws Exception {
        JsonObject v=new JsonParser().parse(new String(Files.readAllBytes(Paths.get("fixtures/runner-hardware-normalized.json")),StandardCharsets.UTF_8)).getAsJsonObject();
        RunnerScenario old=RunnerScenario.parse(v.toString());v.addProperty("schemaVersion",4);v.add("containers",new JsonArray());v.getAsJsonObject("expect").add("containers",new JsonArray());
        RunnerScenario current=RunnerScenario.parse(v.toString());assertEquals(old.hardware,current.hardware);assertEquals(old.mode,current.mode);
    }
}
