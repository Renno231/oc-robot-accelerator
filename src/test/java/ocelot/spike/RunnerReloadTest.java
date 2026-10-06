package ocelot.spike;

import com.google.gson.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class RunnerReloadTest {
    private JsonObject manifest() {
        return new JsonParser().parse("{\"scenario\":\"transfer\",\"drones\":[{\"uuid\":\"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\",\"address\":\"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb\"}]}").getAsJsonObject();
    }
    @Test public void exactIdentitySet() {RunnerDrones.validateReload(manifest(),"transfer",1);}
    @Test public void scenarioAndCountCannotChange() {
        for(boolean wrongScenario:new boolean[]{true,false}) {
            try {RunnerDrones.validateReload(manifest(),wrongScenario?"other":"transfer",wrongScenario?1:2);fail();}
            catch(IllegalStateException expected) {assertTrue(expected.getMessage().startsWith("reload_"));}
        }
    }
    @Test public void duplicateEntitiesCannotBeAdopted() {
        JsonObject data=manifest();data.getAsJsonArray("drones").add(data.getAsJsonArray("drones").get(0));
        try {RunnerDrones.validateReload(data,"transfer",2);fail();}
        catch(IllegalStateException expected) {assertEquals("reload_duplicate_drone",expected.getMessage());}
    }
    @Test(expected=IllegalArgumentException.class) public void malformedNativeIdentityFails() {
        JsonObject data=manifest();data.getAsJsonArray("drones").get(0).getAsJsonObject().addProperty("uuid","not-uuid");
        RunnerDrones.validateReload(data,"transfer",1);
    }
}
