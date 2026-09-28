package ocelot.spike;

import org.junit.Test;
import java.nio.charset.StandardCharsets;
import static org.junit.Assert.*;

public class RunnerBoundaryTest {
    @Test public void loadedHostsIncludeEmptyRackAndDroneWithoutRejectingOrdinaryHosts() {
        assertNotNull(getClass().getClassLoader().getResource("li/cil/oc/common/tileentity/Rack.class"));
        assertNotNull(getClass().getClassLoader().getResource("li/cil/oc/common/entity/Drone.class"));
        assertTrue(RunnerRuntime.isMachineHostName("li.cil.oc.common.tileentity.Rack",false));
        assertTrue(RunnerRuntime.isMachineHostName("li.cil.oc.common.entity.Drone",true));
        assertFalse(RunnerRuntime.isMachineHostName("li.cil.oc.common.tileentity.Screen",false));
        assertFalse(RunnerRuntime.isMachineHostName("li.cil.oc.common.tileentity.Rack",true));
        assertFalse(RunnerRuntime.isMachineHostName("li.cil.oc.common.entity.Drone",false));
        assertFalse(RunnerRuntime.isMachineTile(net.minecraft.tileentity.TileEntity.class));
        assertFalse(RunnerRuntime.isMachineEntity(net.minecraft.entity.Entity.class));
    }
    @Test public void creativePowerExceptionRequiresEmptyNonrunningCase() {
        net.minecraft.init.Bootstrap.register();
        net.minecraft.inventory.InventoryBasic slots=new net.minecraft.inventory.InventoryBasic("source",false,3);
        assertTrue(RunnerRuntime.emptyPowerSource(true,false,slots));
        assertFalse(RunnerRuntime.emptyPowerSource(false,false,slots));
        assertFalse(RunnerRuntime.emptyPowerSource(true,true,slots));
        slots.setInventorySlotContents(2,new net.minecraft.item.ItemStack(new net.minecraft.item.Item()));
        assertFalse(RunnerRuntime.emptyPowerSource(true,false,slots));
    }
    @Test public void shutdownClosureIsScheduledOnlyForActualStoppingState() {
        assertFalse(RunnerRuntime.needsNativeClose("Stopped"));
        assertFalse(RunnerRuntime.needsNativeClose("Yielded"));
        assertFalse(RunnerRuntime.needsNativeClose("SynchronizedCall"));
        assertTrue(RunnerRuntime.needsNativeClose("Stopping"));
    }
    @Test public void observationWireBytesUseOneLfEvenOnWindowsAndCountActualUtf8Bytes() throws Exception {
        String line="{\"label\":\"é\"}";
        byte[] encoded=RunnerObservations.wireLine(line);
        assertEquals(line+"\n",new String(encoded,StandardCharsets.UTF_8));
        assertEquals(line.getBytes(StandardCharsets.UTF_8).length+1,encoded.length);
        assertEquals(10,RunnerObservations.wireLine("123456789").length);
    }
    @Test public void stallClockDoesNotAdvanceOnEmptyDeltaFollowingChangedRegion() {
        RunnerObservations.StallClock clock=new RunnerObservations.StallClock();
        assertEquals(1,clock.observe(1,"robot",true));
        assertEquals(5,clock.observe(5,"robot",true));
        assertEquals(5,clock.observe(6,"robot",false));
        assertEquals(5,clock.observe(7,"robot",false));
        assertEquals(8,clock.observe(8,"moved",false));
        assertEquals(8,clock.observe(9,"moved",false));
    }
}
