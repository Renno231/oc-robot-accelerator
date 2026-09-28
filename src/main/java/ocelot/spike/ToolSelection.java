package ocelot.spike;

import com.google.gson.*;
import java.util.Map;

/** Private, bounded fixture input; actual tool behavior remains owned by its Forge mod. */
final class ToolSelection {
    final String item, nbt;
    final int metadata;
    private ToolSelection(String item, int metadata, String nbt) {
        this.item = item; this.metadata = metadata; this.nbt = nbt;
    }
    static ToolSelection parse(String text) {
        try {
            if (text.length() > 8192) throw new IllegalArgumentException("Tool selection exceeds 8KiB");
            JsonElement parsed = new JsonParser().parse(text);
            if (!parsed.isJsonObject()) throw new IllegalArgumentException("Tool selection must be an object");
            JsonObject json = parsed.getAsJsonObject();
            for (Map.Entry<String, JsonElement> entry : json.entrySet())
                if (!entry.getKey().equals("item") && !entry.getKey().equals("metadata") && !entry.getKey().equals("nbt"))
                    throw new IllegalArgumentException("Unknown tool field: " + entry.getKey());
            String item = string(json, "item", "minecraft:diamond_pickaxe");
            String nbt = string(json, "nbt", "{}");
            if (!item.matches("[a-z0-9_.-]+:[a-z0-9_./-]+")) throw new IllegalArgumentException("Namespaced tool registry ID required");
            int metadata = 0;
            if (json.has("metadata")) {
                JsonElement value = json.get("metadata");
                if (!value.isJsonPrimitive() || !value.getAsJsonPrimitive().isNumber() || !value.getAsString().matches("[0-9]{1,5}"))
                    throw new IllegalArgumentException("Tool metadata must be an integer");
                metadata = value.getAsInt();
                if (metadata > 32767) throw new IllegalArgumentException("Tool metadata bound");
            }
            // Conservative structural bound, including brackets inside strings, before the native SNBT parser.
            if (nbt.length() > 4096 || nbt.chars().filter(c -> c == '{' || c == '[').count() > 64)
                throw new IllegalArgumentException("Tool NBT bound");
            return new ToolSelection(item, metadata, nbt);
        } catch (JsonParseException | IllegalStateException e) { throw new IllegalArgumentException("Invalid tool selection", e); }
    }
    private static String string(JsonObject json, String key, String fallback) {
        if (!json.has(key)) return fallback;
        JsonElement value = json.get(key);
        if (!value.isJsonPrimitive() || !value.getAsJsonPrimitive().isString()) throw new IllegalArgumentException(key + " must be a string");
        return value.getAsString();
    }
}
