package ocelot.spike;

import com.google.gson.*;
import java.util.Map;

/** Bounded variations of one fixture, including an explicitly prepared task boundary. */
final class Scenario {
    final int laps;
    final boolean trace;
    final boolean preparedStart;
    private Scenario(int laps, boolean trace, boolean preparedStart) {
        this.laps = laps; this.trace = trace; this.preparedStart = preparedStart;
    }
    static Scenario parse(String text) {
        try {
            JsonElement parsed = new JsonParser().parse(text);
            if (!parsed.isJsonObject()) throw new IllegalArgumentException("Scenario object required");
            int laps = 8; boolean trace = true, preparedStart = false;
            for (Map.Entry<String, JsonElement> entry : parsed.getAsJsonObject().entrySet()) {
                JsonElement value = entry.getValue();
                if (entry.getKey().equals("laps") && value.isJsonPrimitive() && value.getAsJsonPrimitive().isNumber()) {
                    laps = value.getAsBigDecimal().intValueExact();
                    if (laps < 1 || laps > 256) throw new IllegalArgumentException("laps must be 1..256");
                } else if (entry.getKey().equals("trace") && value.isJsonPrimitive() && value.getAsJsonPrimitive().isBoolean()) {
                    trace = value.getAsBoolean();
                } else if (entry.getKey().equals("preparedStart") && value.isJsonPrimitive() && value.getAsJsonPrimitive().isBoolean()) {
                    preparedStart = value.getAsBoolean();
                } else throw new IllegalArgumentException("Unknown/invalid scenario key: " + entry.getKey());
            }
            return new Scenario(laps, trace, preparedStart);
        } catch (RuntimeException error) { throw new IllegalArgumentException("Invalid scenario", error); }
    }
}
