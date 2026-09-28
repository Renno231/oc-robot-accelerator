package ocelot.spike;

import org.junit.Test;
import com.google.gson.JsonObject;
import static org.junit.Assert.*;
import java.io.IOException;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.concurrent.atomic.AtomicInteger;
import li.cil.oc.api.fs.FileSystem;
import li.cil.oc.api.fs.Handle;

/** The OC ZIP filesystem resolves assets from the supplied class' actual JAR. */
public class RunnerProgramTest {
    @Test public void copiedWorldReservedDiskCollisionFailsWithoutErasingMarkerOrUserFiles() throws Exception {
        Path save=Files.createTempDirectory("runner-copied-world-");
        Path disk=save.resolve("opencomputers/robot-runner-disk");
        Path outcome=disk.resolve("home/runner-outcome");
        Path extra=disk.resolve("home/program/user-output.txt");
        Files.createDirectories(extra.getParent());
        Files.write(outcome,"returned\n".getBytes(StandardCharsets.UTF_8));
        Files.write(extra,"keep".getBytes(StandardCharsets.UTF_8));
        try {
            RunnerProgram.requireFreshDisk(save,"opencomputers/","robot-runner-disk");
            fail("existing reserved disk may carry a stale success marker");
        } catch(IllegalStateException expected) {assertTrue(expected.getMessage().contains("runner_disk_collision"));}
        assertEquals("returned\n",new String(Files.readAllBytes(outcome),StandardCharsets.UTF_8));
        assertEquals("keep",new String(Files.readAllBytes(extra),StandardCharsets.UTF_8));
        Files.delete(extra);Files.delete(extra.getParent());Files.delete(outcome);
        Files.delete(outcome.getParent());Files.delete(disk);Files.delete(disk.getParent());Files.delete(save);
    }
    @Test public void finalArtifactFailuresCannotLeavePassingReasonAndPreserveEarlierFailure() {
        JsonObject result=new JsonObject();result.addProperty("runnerArtifactError","IOException:program_console_limit");
        assertEquals("runner_artifact_error:IOException:program_console_limit",RobotSpike.runnerFinalReason(true,"passed",result));
        assertEquals("tick_limit;runner_artifact_error:IOException:program_console_limit",RobotSpike.runnerFinalReason(false,"tick_limit",result));
        assertEquals("passed",RobotSpike.runnerFinalReason(true,"passed",new JsonObject()));
    }
    @Test public void observerReusesLiveFilesystemAndClosesOnlyItsOwnHandles() throws Exception {
        Path root=Files.createTempDirectory("runner-observer-");
        final byte[][] current={null}; final int[] readOffset={0};
        AtomicInteger open=new AtomicInteger(),closed=new AtomicInteger(),observerClosed=new AtomicInteger();
        Handle handle=(Handle)Proxy.newProxyInstance(getClass().getClassLoader(),new Class<?>[]{Handle.class},(proxy,method,args)->{
            if(method.getName().equals("read")) {
                byte[] target=(byte[])args[0];byte[] content=current[0];
                if(readOffset[0]>=content.length) return -1;
                int count=Math.min(target.length,content.length-readOffset[0]);
                System.arraycopy(content,readOffset[0],target,0,count);readOffset[0]+=count;return count;
            }
            if(method.getName().equals("close")) {closed.incrementAndGet();return null;}
            throw new AssertionError(method.getName());
        });
        FileSystem fs=(FileSystem)Proxy.newProxyInstance(getClass().getClassLoader(),new Class<?>[]{FileSystem.class},(proxy,method,args)->{
            String name=method.getName();
            if(!name.equals("close")) assertTrue("shared filesystem observation must hold native monitor",Thread.holdsLock(proxy));
            String path=args!=null && args.length>0 && args[0] instanceof String?(String)args[0]:"";
            if(name.equals("size")) return path.equals("home/runner-console.log")?0L:current[0]==null?0L:(long)current[0].length;
            if(name.equals("exists")) return current[0]!=null;
            if(name.equals("open")) {open.incrementAndGet();readOffset[0]=0;return 1;}
            if(name.equals("getHandle")) return handle;
            if(name.equals("close")) {observerClosed.incrementAndGet();return null;}
            throw new AssertionError(name);
        });
        RunnerProgram program=new RunnerProgram(root,fs);
        try {
            assertEquals("",program.outcome());
            current[0]="returned\n".getBytes(StandardCharsets.UTF_8);
            assertEquals("returned\n",program.outcome());
            current[0]="error\nchanged".getBytes(StandardCharsets.UTF_8);
            assertEquals("error\nchanged",program.outcome());
            assertEquals(2,open.get()); assertEquals(2,closed.get());
            current[0]=new byte[8209];
            try {program.outcome();fail("outcome cap not enforced");} catch(IOException expected) {assertTrue(expected.getMessage().contains("program_outcome_limit"));}
        } finally {program.close();Files.delete(root);}
        assertEquals(1,observerClosed.get());
        RunnerProgram borrowed=new RunnerProgram(root);
        assertFalse(borrowed.observing()); borrowed.borrow(fs); assertTrue(borrowed.observing());
        current[0]="returned\n".getBytes(StandardCharsets.UTF_8);
        assertEquals("returned\n",borrowed.outcome()); borrowed.close();
        assertFalse(borrowed.observing()); assertEquals("must not close robot-owned filesystem",1,observerClosed.get());
    }
    @Test public void queuedYieldedWaitsForOneCompletedWorkerBeforeAdvancingTick() {
        assertTrue(RunnerRuntime.runnerWorkerNeedsTime("Yielded",false,false));
        assertFalse(RunnerRuntime.runnerWorkerNeedsTime("Yielded",false,true));
        assertTrue(RunnerRuntime.runnerWorkerNeedsTime("Yielded",true,true));
        assertTrue(RunnerRuntime.runnerWorkerNeedsTime("Running",true,true));
        assertFalse(RunnerRuntime.runnerWorkerNeedsTime("SynchronizedCall",false,false));
        assertFalse(RunnerRuntime.runnerWorkerNeedsTime("Stopped",false,false));
    }
    @Test public void firstObservationAndEnergyWaitForComponentNetworkBeforeBoot() {
        assertFalse(RunnerRuntime.shouldPreparePreboot(1,false,false));
        assertFalse(RunnerRuntime.shouldPreparePreboot(3,false,false));
        assertFalse(RunnerRuntime.shouldPreparePreboot(2,true,false));
        assertTrue(RunnerRuntime.shouldPreparePreboot(3,true,false));
        assertFalse(RunnerRuntime.shouldPreparePreboot(4,true,true));
    }
    @Test public void openOsAnchorIsPinnedOcArtifactNotControlJar() {
        String oc = li.cil.oc.OpenComputers.class.getProtectionDomain().getCodeSource().getLocation().toString();
        String control = RobotSpike.class.getProtectionDomain().getCodeSource().getLocation().toString();
        assertNotEquals("OpenOS must resolve from OC artifact, not robot-spike",control,oc);
        assertNotNull(li.cil.oc.OpenComputers.class.getClassLoader().getResource("assets/opencomputers/loot/openos/init.lua"));
        assertNotNull(li.cil.oc.OpenComputers.class.getClassLoader().getResource("assets/opencomputers/lua/component/robot/lib/robot.lua"));
    }
}
