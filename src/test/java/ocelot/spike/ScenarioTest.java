package ocelot.spike;

import org.junit.Test;
import static org.junit.Assert.*;

public class ScenarioTest {
    @Test public void defaultsAndBounds() {
        assertEquals(8, Scenario.parse("{}").laps);
        assertTrue(Scenario.parse("{}").trace);
        assertEquals(128, Scenario.parse("{\"laps\":128,\"trace\":false}").laps);
        assertFalse(Scenario.parse("{\"trace\":false}").trace);
    }
    @Test public void preparedStartIsAnExplicitOptIn() {
        assertFalse(Scenario.parse("{}").preparedStart);
        assertTrue(Scenario.parse("{\"preparedStart\":true}").preparedStart);
        assertFalse(Scenario.parse("{\"preparedStart\":false}").preparedStart);
    }
    @Test public void rejectsInvalidOrUnknown() {
        for (String text : new String[]{"[]", "{\"laps\":0}", "{\"laps\":257}", "{\"laps\":1.5}",
                "{\"laps\":\"8\"}", "{\"trace\":\"false\"}", "{\"preparedStart\":1}", "{\"skipTicks\":true}"}) {
            try { Scenario.parse(text); fail(text); } catch (IllegalArgumentException expected) {}
        }
    }
}
