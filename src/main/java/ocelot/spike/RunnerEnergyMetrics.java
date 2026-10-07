package ocelot.spike;

import java.util.IdentityHashMap;
import li.cil.oc.api.network.ComponentConnector;

/** Observes successful native Machine.update power debits, including sleeping.
 * Does not replace a cost, state predicate, connector, or recharge operation. */
public final class RunnerEnergyMetrics {
    private static final IdentityHashMap<Object,Double> consumed=new IdentityHashMap<>();
    private RunnerEnergyMetrics() {}
    static synchronized void track(Object machine) {consumed.put(machine,0.0);}
    static synchronized double consumed(Object machine) {return consumed.getOrDefault(machine,0.0);}
    public static boolean debit(ComponentConnector connector,double amount,Object machine) {
        boolean success=connector.tryChangeBuffer(amount);
        if(success && amount<0) synchronized(RunnerEnergyMetrics.class) {
            Double value=consumed.get(machine);
            if(value!=null) consumed.put(machine,value-amount);
        }
        return success;
    }
    public static boolean wirelessDebit(ComponentConnector connector,double amount,li.cil.oc.server.component.WirelessNetworkCard card) {
        Object host=card.host();
        if(host instanceof li.cil.oc.common.entity.Drone)
            return debit(connector,amount,((li.cil.oc.common.entity.Drone)host).machine());
        return connector.tryChangeBuffer(amount);
    }
}
