package ocelot.spike;

import li.cil.oc.api.network.Message;
import li.cil.oc.api.network.Visibility;
import li.cil.oc.common.entity.Drone;

/** Observe native stopped notifications before a later native wake can clear an error. */
final class RunnerDroneErrors extends li.cil.oc.api.prefab.AbstractManagedEnvironment {
    private final Drone drone;
    private volatile String error;
    RunnerDroneErrors(Drone drone) {
        this.drone=drone;
        setNode(li.cil.oc.api.Network.newNode(this,Visibility.Network).create());
        drone.machine().node().connect(node());
    }
    @Override public void onMessage(Message message) {
        if(message.source()==drone.machine().node() && message.name().equals("computer.stopped")) observe();
    }
    String observe() {
        error=remember(error,drone.machine().lastError());return error;
    }
    static String remember(String earlier,String current) {return earlier==null?current:earlier;}
    void close() {node().remove();}
}
