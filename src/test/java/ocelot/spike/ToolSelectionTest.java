package ocelot.spike;

import org.junit.Test;
import static org.junit.Assert.*;

public class ToolSelectionTest {
    @Test public void acceptsRegistryMetadataAndNbtForModdedTools() {
        ToolSelection tool = ToolSelection.parse("{\"item\":\"examplemod:aiot\",\"metadata\":2,\"nbt\":\"{Energy:10000}\"}");
        assertEquals("examplemod:aiot", tool.item);
        assertEquals(2, tool.metadata);
        assertEquals("{Energy:10000}", tool.nbt);
    }
    @Test public void defaultsToVanillaPickaxe() {
        assertEquals("minecraft:diamond_pickaxe", ToolSelection.parse("{}").item);
    }
    @Test public void rejectsUnsupportedOrUnboundedInput() {
        for (String text : new String[]{"[]", "{\"class\":\"evil\"}", "{\"item\":\"No Namespace\"}", "{\"metadata\":-1}", "{\"metadata\":0.5}", "{\"nbt\":{}}"}) {
            try { ToolSelection.parse(text); fail(text); }
            catch (IllegalArgumentException expected) { }
        }
    }
}
