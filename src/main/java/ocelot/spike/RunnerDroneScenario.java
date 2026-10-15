package ocelot.spike;

import com.google.gson.*;
import java.util.*;

/** Additional normalized v4 fields, isolated from the legacy robot contract. */
final class RunnerDroneScenario {
    private static final int MAX_DRONES = 16;
    final JsonArray drones, microcontrollers, containers, expectedDrones, expectedContainers;
    final JsonObject computer,secondComputer;
    final JsonArray placedBlocks;
    final JsonArray robots, expectedRobots, containerEdits, droneActions;
    final boolean infiniteEnergy;
    private final JsonObject original;
    RunnerDroneScenario(JsonObject root) {
        original=root;
        JsonObject execution=root.getAsJsonObject("execution");
        if(execution.has("infiniteEnergy") && (!execution.get("infiniteEnergy").isJsonPrimitive() || !execution.get("infiniteEnergy").getAsJsonPrimitive().isBoolean()))
            throw RunnerScenario.bad("infiniteEnergy boolean");
        infiniteEnergy=execution.has("infiniteEnergy") && execution.get("infiniteEnergy").getAsBoolean();
        boolean drone=root.has("drones");
        computer=root.has("computer")?RunnerScenario.object(root.get("computer"),"*"):null;
        secondComputer=root.has("secondComputer")?RunnerScenario.object(root.get("secondComputer"),"*"):null;
        if(secondComputer!=null && computer==null) throw RunnerScenario.bad("secondComputer requires computer");
        if(drone==root.has("robot")) throw RunnerScenario.bad("v4 requires exactly one of robot or drones");
        String keys=drone?"schemaVersion,id,world,drones,containers,execution,observations,expect":
            "schemaVersion,id,world,robot,program,containers,execution,observations,expect";
        RunnerScenario.fields(root,keys+(computer!=null?",computer":"")+(secondComputer!=null?",secondComputer":"")+(root.has("blocks")?",blocks":"")+
            (root.has("robots")?",robots":"")+(root.has("containerEdits")?",containerEdits":"")+(root.has("droneActions")?",droneActions":"")+(root.has("microcontrollers")?",microcontrollers":""));
        if(computer!=null && !drone) throw RunnerScenario.bad("computer requires drones array (may be empty)");
        placedBlocks=root.has("blocks")?RunnerScenario.array(root.get("blocks"),128):new JsonArray();
        drones=drone?RunnerScenario.array(root.get("drones"),MAX_DRONES):new JsonArray();
        microcontrollers=root.has("microcontrollers")?RunnerScenario.array(root.get("microcontrollers"),16):new JsonArray();
        if(root.has("microcontrollers") && (!drone || computer==null)) throw RunnerScenario.bad("microcontrollers require controller computer");
        robots=root.has("robots")?RunnerScenario.array(root.get("robots"),4):new JsonArray();
        if(root.has("robots") && (!drone || robots.size()==0)) throw RunnerScenario.bad("robots require drone mode and count 1..4");
        if(drone && drones.size()==0 && computer==null && robots.size()==0) throw RunnerScenario.bad("drones count 1..16");
        containerEdits=root.has("containerEdits")?RunnerScenario.array(root.get("containerEdits"),64):new JsonArray();
        if(root.has("containerEdits") && !drone) throw RunnerScenario.bad("container edits require drone mode");
        droneActions=root.has("droneActions")?RunnerScenario.array(root.get("droneActions"),64):new JsonArray();
        if(root.has("droneActions") && !drone) throw RunnerScenario.bad("drone actions require drone mode");
        containers=RunnerScenario.array(root.get("containers"),128);
        JsonObject expect=RunnerScenario.object(root.get("expect"),(drone?"blocks,containers,drones":"blocks,inventory,position,containers")+(root.has("robots")?",robots":""));
        expectedRobots=root.has("robots")?RunnerScenario.array(expect.get("robots"),4):new JsonArray();
        expectedDrones=drone?RunnerScenario.array(expect.get("drones"),MAX_DRONES):new JsonArray();
        expectedContainers=RunnerScenario.array(expect.get("containers"),128);
    }
    JsonObject common() {
        JsonObject root=new JsonParser().parse(original.toString()).getAsJsonObject(); root.remove("containers");root.remove("drones");
        root.remove("computer");root.remove("secondComputer");root.remove("blocks");
        root.remove("robots");root.remove("containerEdits");root.remove("droneActions");root.remove("microcontrollers");
        root.getAsJsonObject("execution").remove("infiniteEnergy");
        JsonObject expect=root.getAsJsonObject("expect");expect.remove("drones");expect.remove("containers");
        expect.remove("robots");
        if(drones.size()>0 || computer!=null || robots.size()>0) {
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
        Set<String> robotPositions=new HashSet<>();
        for(int index=0;index<robots.size();index++) {
            JsonObject r=robots.get(index).getAsJsonObject();
            RunnerScenario.fields(r,"position,facing,hardware,program,inventory,energy"+(r.has("assembly")?",assembly":""));
            spec.inside(RunnerScenario.position(r.get("position")));
            if(!robotPositions.add(r.get("position").toString())) throw RunnerScenario.bad("duplicate robot position");
            if(!Arrays.asList("north","south","east","west").contains(RunnerScenario.string(r.get("facing")))) throw RunnerScenario.bad("robot facing");
            RunnerScenario.hardware(r.get("hardware"));
            if(RunnerComputerScenario.number(r.get("energy"),"robot energy")<=0) throw RunnerScenario.bad("robot energy");
            initialSlots(r.get("inventory"),64);
            JsonObject program=RunnerScenario.object(r.get("program"),"directory,entry");
            if(!("robot-program-"+index).equals(RunnerScenario.string(program.get("directory")))) throw RunnerScenario.bad("robot program directory");
            if(!RunnerScenario.path(RunnerScenario.string(program.get("entry"))).endsWith(".lua")) throw RunnerScenario.bad("robot Lua entry");
            if(r.has("assembly")) {
                if(index==0 || index!=robots.size()-1) throw RunnerScenario.bad("assembly must add the last robot to an existing factory");
                JsonObject a=RunnerScenario.object(r.get("assembly"),"source,blocks,request");
                for(JsonElement b:RunnerScenario.array(a.get("blocks"),128)) RunnerScenario.fields(b.getAsJsonObject(),"position,block,properties");
                spec.inside(RunnerScenario.position(a.get("source")));
                boolean source=false;for(JsonElement c:containers) if(c.getAsJsonObject().get("position").equals(a.get("source"))) source=true;
                if(!source) throw RunnerScenario.bad("assembly source must be a declared container");
                RunnerComputerScenario.validate(spec,null,RunnerScenario.array(a.get("blocks"),128));
                JsonObject request=RunnerScenario.object(a.get("request"),"computer,marker,signal");
                int controller=RunnerScenario.integer(request.get("computer"),0,1);
                if((controller==0?computer:secondComputer)==null) throw RunnerScenario.bad("assembly controller absent");
                RunnerScenario.path(RunnerScenario.string(request.get("marker")));
                if(!RunnerScenario.PROP.matcher(RunnerScenario.string(request.get("signal"))).matches()) throw RunnerScenario.bad("assembly signal");
            }
        }
        for(JsonElement e:expectedRobots) {
            JsonObject r=e.getAsJsonObject();RunnerScenario.fields(r,"index"+(r.has("inventory")?",inventory":""));
            RunnerScenario.integer(r.get("index"),0,robots.size()-1);
            if(r.has("inventory")) expectedSlots(r.get("inventory"),85);
        }
        JsonArray devices=new JsonArray();for(JsonElement e:drones) devices.add(e);
        for(JsonElement e:microcontrollers) {
            JsonObject m=e.getAsJsonObject();
            RunnerScenario.fields(m,"position,hardware,eeprom,eepromData"+(m.has("energy")?",energy":""));
            JsonObject d=new JsonParser().parse(m.toString()).getAsJsonObject();d.add("inventory",new JsonArray());devices.add(d);
        }
        for(JsonElement e:devices) {
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
            JsonObject c=RunnerScenario.object(e,"position,block,slots"+(e.isJsonObject() && e.getAsJsonObject().has("properties")?",properties":""));spec.inside(RunnerScenario.position(c.get("position")));
            if(c.has("properties")) {
                JsonObject props=RunnerScenario.object(c.get("properties"),"*");
                if(props.entrySet().size()>16) throw RunnerScenario.bad("properties count");
                for(java.util.Map.Entry<String,JsonElement> prop:props.entrySet())
                    if(!prop.getKey().matches("[A-Za-z0-9_.+-]{1,64}") || !RunnerScenario.string(prop.getValue()).matches("[A-Za-z0-9_.+-]{1,64}")) throw RunnerScenario.bad("property");
            }
            if(!positions.add(c.get("position").toString())) throw RunnerScenario.bad("duplicate container position");
            RunnerScenario.registry(c.get("block"));initialSlots(c.get("slots"),64);
        }
        for(JsonElement r:robots) if(r.getAsJsonObject().has("assembly"))
            for(JsonElement b:r.getAsJsonObject().getAsJsonObject("assembly").getAsJsonArray("blocks"))
                positions.add(b.getAsJsonObject().get("position").toString());
        for(JsonElement e:expectedContainers) {
            JsonObject c=RunnerScenario.object(e,"position,slots");spec.inside(RunnerScenario.position(c.get("position")));
            if(!positions.contains(c.get("position").toString())) throw RunnerScenario.bad("expect container must be declared");
            expectedSlots(c.get("slots"),64);
        }
        for(JsonElement e:containerEdits) {
            JsonObject edit=e.getAsJsonObject();RunnerScenario.fields(edit,"position,slot,count"+
                (edit.has("atTick")?",atTick":"")+(edit.has("request")?",request":"")+(edit.has("expectedCount")?",expectedCount":""));
            spec.inside(RunnerScenario.position(edit.get("position")));
            if(!positions.contains(edit.get("position").toString())) throw RunnerScenario.bad("container edit target must be declared");
            RunnerScenario.integer(edit.get("slot"),1,64);int count=RunnerScenario.integer(edit.get("count"),1,64);
            if(edit.has("expectedCount")) RunnerScenario.integer(edit.get("expectedCount"),count,64);
            if(edit.has("atTick")==edit.has("request")) throw RunnerScenario.bad("container edit requires exactly one trigger");
            if(edit.has("atTick")) RunnerScenario.integer(edit.get("atTick"),0,spec.maxTicks);
            else {
                JsonObject request=RunnerScenario.object(edit.get("request"),"computer,marker,signal");
                int index=RunnerScenario.integer(request.get("computer"),0,1);
                if((index==0?computer:secondComputer)==null) throw RunnerScenario.bad("container edit computer absent");
                RunnerScenario.path(RunnerScenario.string(request.get("marker")));
                if(!RunnerScenario.PROP.matcher(RunnerScenario.string(request.get("signal"))).matches()) throw RunnerScenario.bad("container edit signal");
            }
        }
        for(JsonElement e:droneActions) {
            JsonObject action=RunnerScenario.object(e,"action,drone,to,request");
            if(!"move_drone".equals(RunnerScenario.string(action.get("action")))) throw RunnerScenario.bad("unknown drone action");
            RunnerScenario.integer(action.get("drone"),0,drones.size()-1);
            spec.inside(RunnerScenario.position(action.get("to")));
            JsonObject request=RunnerScenario.object(action.get("request"),"computer,marker,signal");
            int index=RunnerScenario.integer(request.get("computer"),0,1);
            if((index==0?computer:secondComputer)==null) throw RunnerScenario.bad("drone action computer absent");
            RunnerScenario.path(RunnerScenario.string(request.get("marker")));
            if(!RunnerScenario.PROP.matcher(RunnerScenario.string(request.get("signal"))).matches()) throw RunnerScenario.bad("drone action signal");
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
