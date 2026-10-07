package ocelot.spike;

import java.lang.reflect.Proxy;
import li.cil.oc.api.network.ComponentConnector;
import org.junit.Test;
import static org.junit.Assert.*;

public class RunnerEnergyMetricsTest {
    @Test public void observesOnlySuccessfulDebitsWithoutChangingNativeArguments() {
        Object machine=new Object();RunnerEnergyMetrics.track(machine);
        final double[] amount={0};final boolean[] success={true};
        ComponentConnector connector=(ComponentConnector)Proxy.newProxyInstance(getClass().getClassLoader(),new Class[]{ComponentConnector.class},(p,m,a)-> {
            assertEquals("tryChangeBuffer",m.getName());amount[0]=(Double)a[0];return success[0];
        });
        assertTrue(RunnerEnergyMetrics.debit(connector,-.4,machine));assertEquals(-.4,amount[0],0);
        assertEquals(.4,RunnerEnergyMetrics.consumed(machine),0);
        assertTrue(RunnerEnergyMetrics.debit(connector,10,machine));assertEquals(.4,RunnerEnergyMetrics.consumed(machine),0);
        success[0]=false;assertFalse(RunnerEnergyMetrics.debit(connector,-.4,machine));assertEquals(.4,RunnerEnergyMetrics.consumed(machine),0);
    }
}
