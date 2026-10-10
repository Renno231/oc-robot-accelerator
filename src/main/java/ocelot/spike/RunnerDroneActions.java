package ocelot.spike;

import com.google.gson.*;
import java.util.HashSet;
import java.util.Set;

/** Fixture-declared one-shot player relocation; no logistics state is read or written. */
final class RunnerDroneActions {
    interface Environment {
        boolean requested(int computer,String marker);
        void move(int drone,double x,double y,double z);
        void signal(int computer,String name);
    }
    private final JsonArray actions;
    private final Set<Integer> applied=new HashSet<>();
    RunnerDroneActions(JsonArray actions) {this.actions=actions;}
    void tick(Environment environment) {
        for(int index=0;index<actions.size();index++) {
            if(applied.contains(index)) continue;
            JsonObject action=actions.get(index).getAsJsonObject(),request=action.getAsJsonObject("request");
            int computer=request.get("computer").getAsInt();
            if(!environment.requested(computer,request.get("marker").getAsString())) continue;
            JsonArray to=action.getAsJsonArray("to");
            environment.move(action.get("drone").getAsInt(),to.get(0).getAsDouble()+0.5,
                to.get(1).getAsDouble()+0.5,to.get(2).getAsDouble()+0.5);
            applied.add(index);
            environment.signal(computer,request.get("signal").getAsString());
        }
    }
}
