package ocelot.spike;

import com.google.gson.*;
import li.cil.oc.api.machine.Machine;

/** Read-only evidence, not a guest API, timer or sampling workload. */
final class RunnerMachineEvidence {
    static JsonObject power(li.cil.oc.api.network.Connector node) {
        JsonObject result=new JsonObject();
        result.addProperty("energy",node.globalBuffer());result.addProperty("capacity",node.globalBufferSize());
        result.addProperty("localEnergy",node.localBuffer());result.addProperty("localCapacity",node.localBufferSize());
        result.addProperty("boundary","native outbound modem callback");return result;
    }
    static JsonObject components(Machine machine) {
        JsonObject result=new JsonObject();
        synchronized(machine) {
            for(java.util.Map.Entry<String,String> e:machine.components().entrySet()) result.addProperty(e.getKey(),e.getValue());
        }
        return result;
    }
    // Called on the machine's own Java-to-OC modem send boundary, not on the
    // server thread: allocator counters are read on the native Lua owner thread.
    static JsonObject memory(Machine machine) throws ReflectiveOperationException {
        Object architecture=machine.getClass().getMethod("architecture").invoke(machine);
        Object lua=architecture.getClass().getMethod("lua").invoke(architecture);
        int total=((Number)lua.getClass().getMethod("getTotalMemory").invoke(lua)).intValue();
        int free=((Number)lua.getClass().getMethod("getFreeMemory").invoke(lua)).intValue();
        int kernel=((Number)architecture.getClass().getMethod("kernelMemory").invoke(architecture)).intValue();
        double scale=((Number)architecture.getClass().getMethod("ramScale").invoke(architecture)).doubleValue();
        JsonObject result=new JsonObject();result.addProperty("freeMemory",(int)(Math.min(free,total-kernel)/scale));
        result.addProperty("totalMemory",(int)((total-kernel)/scale));result.addProperty("boundary","native outbound modem callback");
        return result;
    }
}
