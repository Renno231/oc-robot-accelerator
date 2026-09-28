package ocelot.spike;

import com.google.gson.*;
import com.google.gson.stream.JsonReader;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.regex.Pattern;

/** Validates the already-normalized Python contract again at the engine boundary. */
final class RunnerScenario {
    static final Pattern ID = Pattern.compile("[a-z0-9_.-]+:[a-z0-9_./-]+"), PROP = Pattern.compile("[A-Za-z0-9_.+-]{1,64}");
    final String id, entry, mode, onFull;
    final int[] min, max, position;
    final JsonArray blocks, inventory, expectedBlocks, expectedInventory;
    final JsonObject tool, expect, hardware;
    final String facing;
    final double energy;
    final Integer randomSeed;
    final int maxTicks, timeoutSeconds, delay, stallTicks, everyTicks, maxBytes;
    final boolean source;
    private RunnerScenario(JsonObject root) {
        fields(root, "schemaVersion,id,program,world,robot,execution,observations,expect");
        int version=integer(root.get("schemaVersion"),1,3);
        id = text(root.get("id"), "[a-z][a-z0-9-]{0,62}", 63);
        JsonObject program = object(root.get("program"), "directory,entry");
        if (!"program".equals(string(program.get("directory")))) throw bad("program directory");
        entry = path(string(program.get("entry")));
        if (!entry.endsWith(".lua")) throw bad("Lua entry");
        JsonObject world = object(root.get("world"), "region,blocks,source");
        source = world.has("source");
        if (source && !"world".equals(string(world.get("source")))) throw bad("world source");
        JsonObject region = object(world.get("region"), "min,max");
        min = position(region.get("min")); max = position(region.get("max"));
        if (regionCells() > 32768 || regionCells() < 1 ||
            ((long)Math.floorDiv(max[0],16)-Math.floorDiv(min[0],16)+1) *
            ((long)Math.floorDiv(max[2],16)-Math.floorDiv(min[2],16)+1) > 64) throw bad("region bounds");
        blocks = array(world.get("blocks"),128);
        for (JsonElement element : blocks) {
            JsonObject block = object(element,"min,max,block,properties");
            int[] low = position(block.get("min")), high = position(block.get("max"));
            inside(low); inside(high);
            for (int i=0;i<3;i++) if (low[i]>high[i]) throw bad("volume order");
            registry(block.get("block"));
            JsonObject props = object(block.get("properties"), "*");
            if (props.entrySet().size()>16) throw bad("properties count");
            for (Map.Entry<String,JsonElement> e:props.entrySet()) {
                if (!PROP.matcher(e.getKey()).matches() || !PROP.matcher(string(e.getValue())).matches()) throw bad("property");
            }
        }
        JsonObject robot = object(root.get("robot"), "position,facing,hardware,energy,tool,inventory"+(version==3?",randomSeed":""));
        randomSeed=robot.has("randomSeed")?integer(robot.get("randomSeed"),0,Integer.MAX_VALUE):null;
        position = position(robot.get("position")); inside(position);
        hardware=version==3?hardware(robot.get("hardware")):null;
        if (version<3 && !"tier3".equals(string(robot.get("hardware")))) throw bad("hardware");
        facing = string(robot.get("facing"));
        if (!Arrays.asList("north","south","east","west").contains(facing)) throw bad("facing");
        try { energy = robot.get("energy").getAsDouble(); }
        catch (RuntimeException e) { throw bad("energy"); }
        if (!robot.get("energy").isJsonPrimitive() || !robot.get("energy").getAsJsonPrimitive().isNumber() ||
            !Double.isFinite(energy) || energy<=0 || energy>(version==3?2147483647:50000)) throw bad("energy");
        tool = item(robot.get("tool"),false);
        int capacity=version==3?64:16;
        inventory = array(robot.get("inventory"),capacity); Set<Integer> slots = new HashSet<>();
        for (JsonElement element:inventory) {
            JsonObject item = item(element,true,capacity);
            if (!slots.add(integer(item.get("slot"),1,capacity))) throw bad("duplicate slot");
        }
        JsonObject execution = object(root.get("execution"),"mode,maxTicks,timeoutSeconds,executionDelayMillis,stallTicks");
        mode = string(execution.get("mode"));
        if (!mode.equals("baseline") && !mode.equals("coordinated") && !(version==3 && mode.equals("paced"))) throw bad("mode");
        maxTicks=integer(execution.get("maxTicks"),1,version==1?10000:1728000);
        timeoutSeconds=integer(execution.get("timeoutSeconds"),1,version==1?600:90000);
        delay=integer(execution.get("executionDelayMillis"),0,12);
        if (delay!=0 && delay!=12) throw bad("delay");
        stallTicks=integer(execution.get("stallTicks"),0,version==1?10000:1728000);
        JsonObject observations=object(root.get("observations"),version==1?"everyTicks":"everyTicks,maxBytes,onFull");
        everyTicks=integer(observations.get("everyTicks"),1,200);
        maxBytes=version==1?33554432:integer(observations.get("maxBytes"),1048576,33554432);
        onFull=version==1?"fail":string(observations.get("onFull"));
        if(!onFull.equals("stop") && !onFull.equals("fail")) throw bad("onFull");
        expect=object(root.get("expect"),"position,blocks,inventory");
        if (expect.has("position")) inside(position(expect.get("position")));
        expectedBlocks=array(expect.get("blocks"),256);
        for (JsonElement element:expectedBlocks) {
            JsonObject b=object(element,"position,block"); inside(position(b.get("position"))); registry(b.get("block"));
        }
        expectedInventory=array(expect.get("inventory"),64);
        for (JsonElement element:expectedInventory) {
            JsonObject i=object(element,"item,minCount"); registry(i.get("item")); integer(i.get("minCount"),0,1024);
        }
    }
    int regionCells() {
        long volume=1;
        for(int i=0;i<3;i++) volume*=((long)max[i]-min[i]+1);
        return volume<0 || volume>Integer.MAX_VALUE ? -1 : (int)volume;
    }
    void inside(int[] p) { for(int i=0;i<3;i++) if(p[i]<min[i] || p[i]>max[i]) throw bad("outside region"); }
    static RunnerScenario parse(String json) {
        if (json.getBytes(StandardCharsets.UTF_8).length > 128*1024) throw bad("manifest bytes");
        try {
            JsonReader reader = new JsonReader(new StringReader(json)); reader.setLenient(false);
            JsonElement element = unique(reader,0);
            if (reader.peek()!=com.google.gson.stream.JsonToken.END_DOCUMENT) throw bad("trailing JSON");
            return new RunnerScenario(element.getAsJsonObject());
        } catch (IOException | IllegalStateException | UnsupportedOperationException e) { throw bad("invalid JSON: " + e.getMessage()); }
    }
    private static JsonElement unique(JsonReader r,int depth) throws IOException {
        if (depth>32) throw bad("JSON nesting");
        switch(r.peek()) {
            case BEGIN_OBJECT:
                JsonObject o=new JsonObject(); r.beginObject();
                while(r.hasNext()) { String key=r.nextName(); if(o.has(key)) throw bad("duplicate JSON key"); o.add(key,unique(r,depth+1)); }
                r.endObject(); return o;
            case BEGIN_ARRAY:
                JsonArray a=new JsonArray(); r.beginArray(); while(r.hasNext()) a.add(unique(r,depth+1)); r.endArray(); return a;
            case STRING: return new JsonPrimitive(r.nextString());
            case NUMBER: return new JsonPrimitive(new com.google.gson.internal.LazilyParsedNumber(r.nextString()));
            case BOOLEAN: return new JsonPrimitive(r.nextBoolean());
            case NULL: r.nextNull(); return JsonNull.INSTANCE;
            default: throw bad("JSON token");
        }
    }
    static JsonObject object(JsonElement e,String keys) {
        if (e==null || !e.isJsonObject()) throw bad("object required");
        JsonObject o=e.getAsJsonObject(); fields(o,keys); return o;
    }
    static void fields(JsonObject o,String keys) {
        if (!keys.equals("*")) {
            Set<String> allowed=new HashSet<>(Arrays.asList(keys.split(",")));
            Set<String> present=new HashSet<>(); for(Map.Entry<String,JsonElement> e:o.entrySet()) present.add(e.getKey());
            if (!allowed.equals(present)) {
                // Optional fields stay absent rather than gaining implicit values.
                Set<String> missing=new HashSet<>(allowed); missing.removeAll(present);
                if (!allowed.containsAll(present) || !Arrays.asList("source","position","randomSeed").containsAll(missing)) throw bad("object fields: "+keys);
            }
        }
    }
    static JsonArray array(JsonElement e,int max) { if(e==null || !e.isJsonArray() || e.getAsJsonArray().size()>max) throw bad("array count"); return e.getAsJsonArray(); }
    static int integer(JsonElement e,int lo,int hi) {
        if(e==null || !e.isJsonPrimitive() || !e.getAsJsonPrimitive().isNumber()) throw bad("integer");
        String value=e.getAsString();
        if(!value.matches("-?(0|[1-9][0-9]*)")) throw bad("integer");
        try {int n=Integer.parseInt(value); if(n>=lo && n<=hi) return n;} catch(NumberFormatException ignored) { }
        throw bad("integer range");
    }
    static String string(JsonElement e) { if(e==null || !e.isJsonPrimitive() || !e.getAsJsonPrimitive().isString()) throw bad("string"); return e.getAsString(); }
    static String text(JsonElement e,String regex,int bytes) {String s=string(e); if(s.getBytes(StandardCharsets.UTF_8).length>bytes || !s.matches(regex)) throw bad("text"); return s;}
    static void registry(JsonElement e) {text(e,ID.pattern(),128);}
    static int[] position(JsonElement e) {JsonArray a=array(e,3); if(a.size()!=3) throw bad("position"); return new int[]{integer(a.get(0),-1000000,1000000),integer(a.get(1),1,254),integer(a.get(2),-1000000,1000000)};}
    static String path(String s) {
        if(s.isEmpty() || s.getBytes(StandardCharsets.UTF_8).length>240) throw bad("path");
        for(String segment:s.split("/",-1)) {
            if(segment.isEmpty() || segment.equals(".") || segment.equals("..") || segment.endsWith(".") || segment.endsWith(" ") || segment.matches("(?i)(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(\\..*)?") || segment.matches(".*[\\\\:*?\"<>|\\x00-\\x1f].*")) throw bad("path");
        }
        return s;
    }
    private static JsonObject hardware(JsonElement e) {
        JsonObject h=object(e,"tier,cpu,memory,cards,upgrades,storage,bootDrive,containers");
        if(!new JsonPrimitive("creative").equals(h.get("tier"))) integer(h.get("tier"),1,3);
        componentName(h.get("cpu"));
        String[] names={"memory","cards","upgrades","storage"}; int[] limits={2,3,9,2};
        for(int n=0;n<names.length;n++) {
            JsonArray a=array(h.get(names[n]),limits[n]);
            if((n==0 || n==3) && a.size()==0) throw bad("hardware requires memory/storage");
            for(JsonElement part:a) {if(n==2) upgrade(part);else componentName(part);}
        }
        integer(h.get("bootDrive"),0,h.getAsJsonArray("storage").size()-1);
        for(JsonElement part:array(h.get("containers"),3)) {
            if(!part.isJsonObject()) throw bad("hardware container");
            JsonObject c=part.getAsJsonObject();
            fields(c,c.has("component")?"item,component":"item");
            componentName(c.get("item")); if(c.has("component")) upgrade(c.get("component"));
        }
        return h;
    }
    private static void upgrade(JsonElement e) {
        if(e!=null && e.isJsonPrimitive() && e.getAsJsonPrimitive().isString()) {componentName(e);return;}
        if(e==null || !e.isJsonObject()) throw bad("upgrade configuration");
        JsonObject c=e.getAsJsonObject();
        if(c.has("level")==c.has("experience")) throw bad("experienceupgrade requires level or experience");
        fields(c,c.has("level")?"item,level":"item,experience");
        if(!"experienceupgrade".equals(string(c.get("item")))) throw bad("configured upgrade type");
        if(c.has("level")) integer(c.get("level"),0,30);
        else {
            JsonElement xp=c.get("experience");
            if(!xp.isJsonPrimitive() || !xp.getAsJsonPrimitive().isNumber()) throw bad("experience number");
            double value=xp.getAsDouble();
            if(!Double.isFinite(value) || value<0 || value>2147483647) throw bad("experience range");
        }
    }
    static String componentName(JsonElement e) {return text(e,"[A-Za-z][A-Za-z0-9_]{0,63}",64);}
    static JsonObject item(JsonElement e,boolean inventory) {return item(e,inventory,16);}
    private static JsonObject item(JsonElement e,boolean inventory,int slots) {
        JsonObject o=object(e,inventory?"slot,item,count,metadata,nbt":"item,metadata,nbt");
        registry(o.get("item")); integer(o.get("metadata"),0,32767);
        if(inventory) {integer(o.get("slot"),1,slots);integer(o.get("count"),1,64);}
        String nbt=string(o.get("nbt")); if(nbt.getBytes(StandardCharsets.UTF_8).length>4096) throw bad("NBT bytes");
        int depth=0; char quote=0; boolean escape=false;
        for(char c:nbt.toCharArray()) {
            if(quote!=0) {if(escape) escape=false; else if(c=='\\') escape=true; else if(c==quote) quote=0;}
            else if(c=='\'' || c=='"') quote=c;
            else if(c=='{' || c=='[') {if(++depth>16) throw bad("NBT depth");}
            else if(c=='}' || c==']') {if(--depth<0) throw bad("NBT balance");}
        }
        if(depth!=0 || quote!=0 || !nbt.trim().startsWith("{") || !nbt.trim().endsWith("}")) throw bad("NBT syntax");
        return o;
    }
    static IllegalArgumentException bad(String reason) {return new IllegalArgumentException("runner scenario: "+reason);}
}
