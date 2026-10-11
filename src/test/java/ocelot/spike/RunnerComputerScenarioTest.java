package ocelot.spike;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class RunnerComputerScenarioTest {
    private JsonObject fixture() throws Exception {
        JsonObject v=new JsonParser().parse(new String(Files.readAllBytes(Paths.get("fixtures/runner-public-normalized.json")),StandardCharsets.UTF_8)).getAsJsonObject();
        v.addProperty("schemaVersion",4);v.remove("program");v.remove("robot");v.add("drones",new JsonArray());v.add("containers",new JsonArray());
        v.add("expect",new JsonParser().parse("{\"blocks\":[],\"containers\":[],\"drones\":[]}"));
        v.add("computer",new JsonParser().parse("{\"position\":[0,65,0],\"hardware\":{\"tier\":3,\"cpu\":\"cpu3\",\"memory\":[\"ram6\"],\"cards\":[\"wlancard2\"],\"storage\":[\"hdd3\"],\"bootDrive\":0},\"program\":{\"directory\":\"program\",\"entry\":\"main.lua\"}}"));
        v.add("blocks",new JsonParser().parse("[{\"position\":[1,65,0],\"block\":\"opencomputers:capacitor\",\"properties\":{},\"energy\":1600}]"));return v;
    }
    private void rejects(JsonObject v) {try {RunnerScenario.parse(v.toString());fail("accepted invalid computer scenario");} catch(IllegalArgumentException expected) {}}
    @Test public void computerOnlyNativeContract() throws Exception {
        RunnerScenario s=RunnerScenario.parse(fixture().toString());assertNotNull(s.v4.computer);assertEquals(0,s.v4.drones.size());assertEquals(1,s.v4.placedBlocks.size());
    }
    @Test public void rackKeepsNativeServerCapacityAndStrictFields() throws Exception {
        JsonObject v=fixture(),c=v.getAsJsonObject("computer"),h=c.getAsJsonObject("hardware");
        c.addProperty("kind","rack");
        h.add("memory",new JsonParser().parse("[\"ram6\",\"ram6\",\"ram6\",\"ram6\"]"));
        h.add("buses",new JsonParser().parse("[\"componentbus3\",\"componentbus3\",\"componentbus3\"]"));
        h.add("cards",new JsonParser().parse("[\"graphicscard3\",\"wlancard2\"]"));
        assertEquals("rack",RunnerScenario.parse(v.toString()).v4.computer.get("kind").getAsString());
        h.getAsJsonArray("memory").add(new JsonPrimitive("ram6"));rejects(v);h.getAsJsonArray("memory").remove(4);
        h.getAsJsonArray("buses").add(new JsonPrimitive("componentbus3"));rejects(v);h.getAsJsonArray("buses").remove(3);
        c.addProperty("unexpected",true);rejects(v);c.remove("unexpected");
        c.addProperty("kind","creative");rejects(v);
        c.addProperty("kind","case");rejects(v);
    }
    @Test public void secondComputerHasSeparateProgramAndPosition() throws Exception {
        JsonObject v=fixture();JsonObject second=new JsonParser().parse(v.get("computer").toString()).getAsJsonObject();
        second.add("position",new JsonParser().parse("[-1,65,0]"));second.getAsJsonObject("program").addProperty("directory","second-program");v.add("secondComputer",second);
        assertNotNull(RunnerScenario.parse(v.toString()).v4.secondComputer);
        second.getAsJsonObject("program").addProperty("directory","program");rejects(v);
        second.getAsJsonObject("program").addProperty("directory","second-program");second.add("position",v.getAsJsonObject("computer").get("position"));rejects(v);
        second.add("position",new JsonParser().parse("[-1,65,0]"));v.remove("computer");rejects(v);
    }
    @Test public void finiteHardwareAndBaselineOnly() throws Exception {
        JsonObject v=fixture();v.getAsJsonObject("computer").getAsJsonObject("hardware").addProperty("tier","creative");rejects(v);
        v=fixture();v.getAsJsonObject("execution").addProperty("mode","coordinated");assertEquals("coordinated",RunnerScenario.parse(v.toString()).mode);
        v=fixture();v.getAsJsonObject("computer").getAsJsonObject("program").addProperty("entry","../main.lua");rejects(v);
        v=fixture();v.getAsJsonObject("computer").getAsJsonObject("hardware").addProperty("bootDrive",1);rejects(v);
        v=fixture();v.getAsJsonObject("computer").getAsJsonObject("hardware").add("memory",new JsonArray());rejects(v);
    }
    @Test public void placedBlockEnergyAndBounds() throws Exception {
        for(String energy:new String[]{"true","-1","1e999","2147483648"}) {
            JsonObject v=fixture();v.getAsJsonArray("blocks").get(0).getAsJsonObject().add("energy",new JsonParser().parse(energy));rejects(v);
        }
        JsonObject v=fixture();v.getAsJsonArray("blocks").add(v.getAsJsonArray("blocks").get(0));rejects(v);
        v=fixture();v.getAsJsonArray("blocks").get(0).getAsJsonObject().add("position",new JsonParser().parse("[99,65,0]"));rejects(v);
    }
}
