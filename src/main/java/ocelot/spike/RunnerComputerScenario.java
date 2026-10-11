package ocelot.spike;

import com.google.gson.*;
import java.util.*;

/** Normalized finite-powered computer and single-block placement boundary. */
final class RunnerComputerScenario {
    static double number(JsonElement e,String label) {
        if(e==null || !e.isJsonPrimitive() || !e.getAsJsonPrimitive().isNumber()) throw RunnerScenario.bad(label);
        double n=e.getAsDouble();if(!Double.isFinite(n) || n<0 || n>2147483647) throw RunnerScenario.bad(label);return n;
    }
    static void validate(RunnerScenario spec,JsonObject computer,JsonArray blocks) {
        validate(spec,computer,blocks,"program");
    }
    static void validate(RunnerScenario spec,JsonObject computer,JsonArray blocks,String directory) {
        if(computer!=null) {
            RunnerScenario.fields(computer,"position,hardware,program"+(computer.has("kind")?",kind":""));spec.inside(RunnerScenario.position(computer.get("position")));
            String kind=computer.has("kind")?RunnerScenario.string(computer.get("kind")):"case";
            if(!kind.equals("case") && !kind.equals("rack")) throw RunnerScenario.bad("controller kind");
            boolean rack=kind.equals("rack");
            JsonObject h=RunnerScenario.object(computer.get("hardware"),"tier,cpu,memory,cards,storage,bootDrive"+(rack?",buses":""));
            RunnerScenario.integer(h.get("tier"),1,3);RunnerScenario.componentName(h.get("cpu"));
            for(String key:new String[]{"memory","cards","storage"}) {
                JsonArray a=RunnerScenario.array(h.get(key),rack?4:key.equals("cards")?3:2);
                if(!key.equals("cards") && a.size()==0) throw RunnerScenario.bad("computer memory/storage");
                for(JsonElement part:a) RunnerScenario.componentName(part);
            }
            if(rack) for(JsonElement part:RunnerScenario.array(h.get("buses"),3)) RunnerScenario.componentName(part);
            RunnerScenario.integer(h.get("bootDrive"),0,h.getAsJsonArray("storage").size()-1);
            JsonObject p=RunnerScenario.object(computer.get("program"),"directory,entry");
            if(!directory.equals(RunnerScenario.string(p.get("directory")))) throw RunnerScenario.bad("computer program directory");
            if(!RunnerScenario.path(RunnerScenario.string(p.get("entry"))).endsWith(".lua")) throw RunnerScenario.bad("computer Lua entry");
        }
        Set<String> positions=new HashSet<>();
        for(JsonElement e:blocks) {
            JsonObject b=e.getAsJsonObject();RunnerScenario.fields(b,"position,block,properties"+(b.has("energy")?",energy":""));
            spec.inside(RunnerScenario.position(b.get("position")));RunnerScenario.registry(b.get("block"));
            if(!positions.add(b.get("position").toString())) throw RunnerScenario.bad("duplicate placed block position");
            JsonObject props=RunnerScenario.object(b.get("properties"),"*");
            if(props.entrySet().size()>16) throw RunnerScenario.bad("properties count");
            for(Map.Entry<String,JsonElement> p:props.entrySet()) {
                if(!RunnerScenario.PROP.matcher(p.getKey()).matches() || !RunnerScenario.PROP.matcher(RunnerScenario.string(p.getValue())).matches()) throw RunnerScenario.bad("property");
            }
            if(b.has("energy")) number(b.get("energy"),"block energy");
        }
    }
    static void expectation(JsonObject d) {
        if(d.has("minEnergy")) number(d.get("minEnergy"),"minimum drone energy");
        if(d.has("running") && (!d.get("running").isJsonPrimitive() || !d.get("running").getAsJsonPrimitive().isBoolean())) throw RunnerScenario.bad("drone running boolean");
    }
}
