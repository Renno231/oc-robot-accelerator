package ocelot.spike;

import com.google.gson.*;
import java.util.*;

/** Additional normalized v4 fields, isolated from the legacy robot contract. */
final class RunnerDroneScenario {
    final JsonArray drones, containers, expectedDrones, expectedContainers;
    final JsonObject computer,secondComputer;
    final JsonArray placedBlocks;
    private final JsonObject original;
    RunnerDroneScenario(JsonObject root) {
        original=root;
        boolean drone=root.has("drones");
        computer=root.has("computer")?RunnerScenario.object(root.get("computer"),"position,hardware,program"):null;
        secondComputer=root.has("secondComputer")?RunnerScenario.object(root.get("secondComputer"),"position,hardware,program"):null;
        if(secondComputer!=null && computer==null) throw RunnerScenario.bad("secondComputer requires computer");
        if(drone==root.has("robot")) throw RunnerScenario.bad("v4 requires exactly one of robot or drones");
        String keys=drone?"schemaVersion,id,world,drones,containers,execution,observations,expect":
            "schemaVersion,id,world,robot,program,containers,execution,observations,expect";
        RunnerScenario.fields(root,keys+(computer!=null?",computer":"")+(secondComputer!=null?",secondComputer":"")+(root.has("blocks")?",blocks":""));
        if(computer!=null && !drone) throw RunnerScenario.bad("computer requires drones array (may be empty)");
        placedBlocks=root.has("blocks")?RunnerScenario.array(root.get("blocks"),128):new JsonArray();
        drones=drone?RunnerScenario.array(root.get("drones"),4):new JsonArray();
        if(drone && drones.size()==0 && computer==null) throw RunnerScenario.bad("drones count 1..4");
        containers=RunnerScenario.array(root.get("containers"),64);
        JsonObject expect=RunnerScenario.object(root.get("expect"),drone?"blocks,containers,drones":"blocks,inventory,position,containers");
        expectedDrones=drone?RunnerScenario.array(expect.get("drones"),4):new JsonArray();
        expectedContainers=RunnerScenario.array(expect.get("containers"),64);
    }
    JsonObject common() {
        JsonObject root=new JsonParser().parse(original.toString()).getAsJsonObject(); root.remove("containers");root.remove("drones");
        root.remove("computer");root.remove("secondComputer");root.remove("blocks");
        JsonObject expect=root.getAsJsonObject("expect");expect.remove("drones");expect.remove("containers");
        if(drones.size()>0 || computer!=null) {
            root.addProperty("schemaVersion",2);
            JsonObject program=new JsonObject();program.addProperty("directory","program");program.addProperty("entry","main.lua");root.add("program",program);
            JsonObject robot=new JsonObject();robot.add("position",root.getAsJsonObject("world").getAsJsonObject("region").get("min"));
            robot.addProperty("facing","north");robot.addProperty("hardware","tier3");robot.addProperty("energy",20000);
            JsonObject tool=new JsonObject();tool.addProperty("item","minecraft:diamond_pickaxe");tool.addProperty("metadata",0);tool.addProperty("nbt","{}");robot.add("tool",tool);
            robot.add("inventory",new JsonArray());root.add("robot",robot);expect.add("inventory",new JsonArray());
        } else root.addProperty("schemaVersion",3);
        return root;
    }
    void validate(RunnerScenario spec) {
        RunnerComputerScenario.validate(spec,computer,placedBlocks);
        if(secondComputer!=null) {
            RunnerComputerScenario.validate(spec,secondComputer,new JsonArray(),"second-program");
            if(secondComputer.get("position").equals(computer.get("position"))) throw RunnerScenario.bad("duplicate computer position");
        }
        for(JsonElement e:drones) {
            JsonObject d=e.getAsJsonObject();
            RunnerScenario.fields(d,d.has("energy")?"position,hardware,eeprom,eepromData,inventory,energy":"position,hardware,eeprom,eepromData,inventory");
            spec.inside(RunnerScenario.position(d.get("position")));
            RunnerScenario.path(RunnerScenario.string(d.get("eeprom")));
            if(!d.get("eeprom").getAsString().endsWith(".lua")) throw RunnerScenario.bad("EEPROM Lua path");
            RunnerScenario.string(d.get("eepromData"));
            if(d.has("energy")) {
                JsonElement v=d.get("energy");double energy=v.getAsDouble();
                if(!v.isJsonPrimitive() || !v.getAsJsonPrimitive().isNumber() || !Double.isFinite(energy) || energy<=0 || energy>2147483647)
                    throw RunnerScenario.bad("drone energy");
            }
            JsonObject h=RunnerScenario.object(d.get("hardware"),"tier,cpu,memory,cards,upgrades");
            if(!new JsonPrimitive("creative").equals(h.get("tier"))) RunnerScenario.integer(h.get("tier"),1,2);
            RunnerScenario.componentName(h.get("cpu"));
            String[] keys={"memory","cards","upgrades"};int[] bounds={2,3,9};
            for(int k=0;k<keys.length;k++) {
                JsonArray a=RunnerScenario.array(h.get(keys[k]),bounds[k]);
                if(k==0 && a.size()==0) throw RunnerScenario.bad("drone memory");
                for(JsonElement part:a) RunnerScenario.componentName(part);
            }
            initialSlots(d.get("inventory"),8);
        }
        Set<String> positions=new HashSet<>();
        for(JsonElement e:containers) {
            JsonObject c=RunnerScenario.object(e,"position,block,slots");spec.inside(RunnerScenario.position(c.get("position")));
            if(!positions.add(c.get("position").toString())) throw RunnerScenario.bad("duplicate container position");
            RunnerScenario.registry(c.get("block"));initialSlots(c.get("slots"),64);
        }
        for(JsonElement e:expectedContainers) {
            JsonObject c=RunnerScenario.object(e,"position,slots");spec.inside(RunnerScenario.position(c.get("position")));
            if(!positions.contains(c.get("position").toString())) throw RunnerScenario.bad("expect container must be declared");
            expectedSlots(c.get("slots"),64);
        }
        for(JsonElement e:expectedDrones) {
            JsonObject d=e.getAsJsonObject();
            String keys="index"+(d.has("blockPosition")?",blockPosition":"")+(d.has("inventory")?",inventory":"")+(d.has("minEnergy")?",minEnergy":"")+(d.has("running")?",running":"");RunnerScenario.fields(d,keys);
            RunnerScenario.integer(d.get("index"),0,drones.size()-1);
            if(d.has("blockPosition")) spec.inside(RunnerScenario.position(d.get("blockPosition")));
            if(d.has("inventory")) expectedSlots(d.get("inventory"),8);
            RunnerComputerScenario.expectation(d);
        }
    }
    private static void initialSlots(JsonElement value,int limit) {
        Set<Integer> seen=new HashSet<>();
        for(JsonElement e:RunnerScenario.array(value,limit)) {
            JsonObject i=RunnerScenario.item(e,true,limit);
            if(!seen.add(i.get("slot").getAsInt())) throw RunnerScenario.bad("duplicate slot");
        }
    }
    private static void expectedSlots(JsonElement value,int limit) {
        Set<Integer> seen=new HashSet<>();
        for(JsonElement e:RunnerScenario.array(value,limit)) {
            JsonObject i=e.getAsJsonObject();RunnerScenario.fields(i,i.has("item")?"slot,item,count":"slot,count");
            if(!seen.add(RunnerScenario.integer(i.get("slot"),1,limit))) throw RunnerScenario.bad("duplicate slot");
            int count=RunnerScenario.integer(i.get("count"),0,64);
            if(i.has("item")) RunnerScenario.registry(i.get("item"));
            else if(count>0) throw RunnerScenario.bad("nonempty slot requires item");
        }
    }
}
