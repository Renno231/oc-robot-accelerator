package ocelot.spike;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class RunnerScenarioTest {
    private JsonObject fixture() throws Exception {
        return new JsonParser().parse(new String(Files.readAllBytes(Paths.get("fixtures/runner-normalized.json")), StandardCharsets.UTF_8)).getAsJsonObject();
    }
    private void rejects(JsonObject object) {
        try { RunnerScenario.parse(object.toString()); fail("accepted unsafe normalized scenario"); }
        catch (IllegalArgumentException expected) { /* boundary rejects malformed input */ }
    }
    @Test public void pythonNormalizedFixture() throws Exception {
        RunnerScenario spec = RunnerScenario.parse(fixture().toString());
        assertEquals("mining", spec.id);
        assertEquals("main.lua", spec.entry);
        assertEquals(20, spec.everyTicks);
        assertEquals(175, spec.regionCells());
    }
    @Test public void pythonPublicNormalizedFixtureAndVersionedBounds() throws Exception {
        JsonObject publicFixture = new JsonParser().parse(new String(Files.readAllBytes(Paths.get("fixtures/runner-public-normalized.json")), StandardCharsets.UTF_8)).getAsJsonObject();
        RunnerScenario spec = RunnerScenario.parse(publicFixture.toString());
        assertEquals(1728000, maximum(publicFixture, "maxTicks", 1728000).maxTicks);
        assertEquals(90000, maximum(publicFixture, "timeoutSeconds", 90000).timeoutSeconds);
        assertEquals(1728000, maximum(publicFixture, "stallTicks", 1728000).stallTicks);
        assertEquals(33554432, spec.maxBytes);
        assertEquals("stop", spec.onFull);
        JsonObject invalid = copy(publicFixture); invalid.getAsJsonObject("observations").addProperty("maxBytes", 1048575); rejects(invalid);
        invalid = copy(publicFixture); invalid.getAsJsonObject("observations").addProperty("onFull", true); rejects(invalid);
        invalid = copy(publicFixture); invalid.getAsJsonObject("execution").addProperty("maxTicks", 1728001); rejects(invalid);
        invalid = fixture(); invalid.getAsJsonObject("observations").addProperty("maxBytes", 33554432); rejects(invalid);
        assertEquals("fail", RunnerScenario.parse(fixture().toString()).onFull);
    }
    @Test public void configurableHardwareBoundary() throws Exception {
        JsonObject fixture = new JsonParser().parse(new String(Files.readAllBytes(Paths.get("fixtures/runner-hardware-normalized.json")), StandardCharsets.UTF_8)).getAsJsonObject();
        assertEquals("stop", RunnerScenario.parse(fixture.toString()).onFull);
        JsonObject invalid = copy(fixture); invalid.getAsJsonObject("robot").addProperty("hardware", "tier3"); rejects(invalid);
        invalid = copy(fixture); invalid.getAsJsonObject("robot").getAsJsonObject("hardware").addProperty("tier", 4); rejects(invalid);
        invalid = copy(fixture); invalid.getAsJsonObject("robot").getAsJsonObject("hardware").addProperty("bootDrive", 1); rejects(invalid);
        invalid = copy(fixture); invalid.getAsJsonObject("robot").getAsJsonObject("hardware").addProperty("cpu", "../cpu3"); rejects(invalid);
        invalid = copy(fixture); invalid.getAsJsonObject("robot").getAsJsonObject("hardware").add("memory", new JsonArray()); rejects(invalid);
        invalid = copy(fixture); invalid.addProperty("schemaVersion", 2); rejects(invalid);
        JsonObject large = copy(fixture); large.getAsJsonObject("robot").addProperty("energy", 100000);
        large.getAsJsonObject("robot").getAsJsonArray("inventory").add(new JsonParser().parse("{\"slot\":64,\"item\":\"minecraft:stone\",\"count\":64,\"metadata\":0,\"nbt\":\"{}\"}"));
        assertEquals(100000, RunnerScenario.parse(large.toString()).energy, 0);
        large.getAsJsonObject("robot").getAsJsonArray("inventory").get(0).getAsJsonObject().addProperty("slot", 65); rejects(large);
    }
    @Test public void creativeTierIsAnExplicitNativeRecipe() throws Exception {
        JsonObject value = new JsonParser().parse(new String(Files.readAllBytes(Paths.get("fixtures/runner-hardware-normalized.json")), StandardCharsets.UTF_8)).getAsJsonObject();
        value.getAsJsonObject("robot").getAsJsonObject("hardware").addProperty("tier","creative");
        assertEquals("creative",RunnerScenario.parse(value.toString()).hardware.get("tier").getAsString());
        for(String tier:new String[]{"4","\"4\"","\"Creative\"","\"3\"","null"}) {
            value.getAsJsonObject("robot").getAsJsonObject("hardware").add("tier",new JsonParser().parse(tier));rejects(value);
        }
    }
    @Test public void experienceStateIsExplicitAndBounded() throws Exception {
        JsonObject value = new JsonParser().parse(new String(Files.readAllBytes(Paths.get("fixtures/runner-hardware-normalized.json")), StandardCharsets.UTF_8)).getAsJsonObject();
        for(String state:new String[]{"{\"item\":\"experienceupgrade\",\"level\":30}","{\"item\":\"experienceupgrade\",\"experience\":400.5}"}) {
            value.getAsJsonObject("robot").getAsJsonObject("hardware").add("upgrades",new JsonParser().parse("["+state+"]"));
            RunnerScenario.parse(value.toString());
        }
        for(String state:new String[]{"{\"item\":\"experienceupgrade\",\"level\":31}",
            "{\"item\":\"experienceupgrade\",\"experience\":-1}","{\"item\":\"experienceupgrade\",\"experience\":true}",
            "{\"item\":\"experienceupgrade\",\"level\":1,\"experience\":10}","{\"item\":\"inventoryupgrade\",\"level\":1}"}) {
            value.getAsJsonObject("robot").getAsJsonObject("hardware").add("upgrades",new JsonParser().parse("["+state+"]")); rejects(value);
        }
    }
    @Test public void pacedModelReferenceIsV3Only() throws Exception {
        JsonObject value = new JsonParser().parse(new String(Files.readAllBytes(Paths.get("fixtures/runner-hardware-normalized.json")), StandardCharsets.UTF_8)).getAsJsonObject();
        value.getAsJsonObject("execution").addProperty("mode","paced");
        assertEquals("paced",RunnerScenario.parse(value.toString()).mode);
        value=fixture();value.getAsJsonObject("execution").addProperty("mode","paced");rejects(value);
        value.addProperty("schemaVersion",2);rejects(value);
    }
    @Test public void optionalRobotRandomSeedIsV3Only() throws Exception {
        JsonObject value = new JsonParser().parse(new String(Files.readAllBytes(Paths.get("fixtures/runner-hardware-normalized.json")), StandardCharsets.UTF_8)).getAsJsonObject();
        for(int seed:new int[]{0,17,Integer.MAX_VALUE}) {
            value.getAsJsonObject("robot").addProperty("randomSeed",seed); RunnerScenario.parse(value.toString());
        }
        for(String seed:new String[]{"-1","2147483648","true","0.5","\"17\"","null"}) {
            value.getAsJsonObject("robot").add("randomSeed",new JsonParser().parse(seed)); rejects(value);
        }
        value=fixture();value.getAsJsonObject("robot").addProperty("randomSeed",17);rejects(value);
    }
    private JsonObject copy(JsonObject fixture) {return new JsonParser().parse(fixture.toString()).getAsJsonObject();}
    private RunnerScenario maximum(JsonObject fixture, String key, int value) {
        JsonObject copy=copy(fixture); copy.getAsJsonObject("execution").addProperty(key,value);
        return RunnerScenario.parse(copy.toString());
    }
    @Test public void strictBoundsAndShapes() throws Exception {
        JsonObject value = fixture(); value.addProperty("unexpected", 1); rejects(value);
        value = fixture(); value.getAsJsonObject("execution").addProperty("maxTicks", true); rejects(value);
        value = fixture(); value.getAsJsonObject("program").addProperty("entry", "../main.lua"); rejects(value);
        value = fixture(); value.getAsJsonObject("world").getAsJsonObject("region").add("max", new JsonParser().parse("[100,68,100]")); rejects(value);
        value = fixture(); value.getAsJsonObject("robot").addProperty("energy", "NaN"); rejects(value);
        value = fixture(); value.getAsJsonObject("observations").addProperty("everyTicks", 0); rejects(value);
        value = fixture(); value.getAsJsonObject("robot").getAsJsonArray("inventory").add(new JsonParser().parse("{\"slot\":1,\"item\":\"minecraft:stone\",\"count\":65,\"metadata\":0,\"nbt\":\"{}\"}")); rejects(value);
        value = fixture(); value.getAsJsonObject("world").getAsJsonArray("blocks").add(new JsonParser().parse("{\"min\":[0,65,0],\"max\":[0,65,0],\"block\":\"minecraft:stone\",\"properties\":{\"unsafe key\":\"a\"}}")); rejects(value);
        value = fixture(); value.getAsJsonObject("robot").getAsJsonObject("tool").addProperty("nbt", "{a:" + new String(new char[17]).replace('\0', '{') + new String(new char[17]).replace('\0', '}') + "}"); rejects(value);
        value = fixture(); value.getAsJsonObject("world").addProperty("source", "../world"); rejects(value);
    }
    @Test public void rejectsDuplicateKeysAndOversized() throws Exception {
        try { RunnerScenario.parse("{\"schemaVersion\":1,\"schemaVersion\":1}"); fail(); }
        catch (IllegalArgumentException expected) { }
        try { RunnerScenario.parse(new String(new char[128 * 1024 + 1]).replace('\0', 'x')); fail(); }
        catch (IllegalArgumentException expected) { }
    }
}
