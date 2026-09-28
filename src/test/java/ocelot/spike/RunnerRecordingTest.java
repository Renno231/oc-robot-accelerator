package ocelot.spike;

import com.google.gson.JsonObject;
import java.io.IOException;
import java.io.InterruptedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import static org.junit.Assert.*;

public class RunnerRecordingTest {
    @Rule public TemporaryFolder folder=new TemporaryFolder();
    private Path root() {return folder.getRoot().toPath();}
    private static String line(int bytes) {StringBuilder s=new StringBuilder();while(s.length()<bytes)s.append('x');return s.toString();}
    private static JsonObject status(Path root) throws IOException {
        return new com.google.gson.JsonParser().parse(new String(Files.readAllBytes(root.resolve("observations-status.json")),StandardCharsets.UTF_8)).getAsJsonObject();
    }
    @Test public void exactFitMultibyteAndCompletePrefixAfterStop() throws Exception {
        try(RunnerRecording recorder=new RunnerRecording(root(),1048576,"stop")) {
            assertEquals(0,status(root()).get("recordsWritten").getAsInt());
            assertTrue(recorder.record("é", "initial",3)); // 3 UTF-8 bytes including LF
            assertTrue(recorder.record(line(1048576-3-1),"sample",5));
            assertFalse(recorder.record("x","sample",8));
            assertFalse(recorder.record("x","final",9));
            assertEquals(9,recorder.lastObservedTick());
            assertEquals(2,recorder.recordsWritten());
            assertEquals(1048576,recorder.bytesWritten());
            assertEquals("byte_limit",status(root()).get("stopReason").getAsString());
        }
        JsonObject coverage=status(root());
        assertEquals(9,coverage.get("lastObservedTick").getAsInt());
        assertEquals(5,coverage.get("lastRecordedTick").getAsInt());
        assertFalse(coverage.get("finalRecorded").getAsBoolean());
        assertEquals(1048576,Files.size(root().resolve("observations.ndjson")));
        assertFalse(Files.exists(root().resolve(".observations-status.json.tmp")));
    }
    @Test public void initialOverflowAndFailPolicyNeverRetainOverCap() throws Exception {
        try(RunnerRecording recorder=new RunnerRecording(root(),1048576,"stop")) {
            try {recorder.record(line(1048576),"initial",3);fail();}
            catch(IOException expected) {assertEquals("observation_limit",expected.getMessage());}
            try {recorder.record("x","final",4);fail("initial failure must not make a final-only recording");}
            catch(IOException expected) {assertEquals("recording_closed",expected.getMessage());}
        }
        assertEquals(0,status(root()).get("recordsWritten").getAsInt());
        assertEquals(0,Files.size(root().resolve("observations.ndjson")));
        Path other=folder.newFolder("fail").toPath();
        try(RunnerRecording recorder=new RunnerRecording(other,1048576,"fail")) {
            assertTrue(recorder.record("x","initial",3));
            try {recorder.record(line(1048575),"final",4);fail();}
            catch(IOException expected) {assertEquals("observation_limit",expected.getMessage());}
        }
        assertFalse(status(other).get("recordingStopped").getAsBoolean());
    }
    @Test public void finalCanTriggerStopAndNoResumptionOrOversizedSampleAfterStop() throws Exception {
        try(RunnerRecording recorder=new RunnerRecording(root(),1048576,"stop")) {
            assertTrue(recorder.record(line(1048575),"initial",3));
            assertFalse(recorder.record("x","final",4));
            try {recorder.record(line(8*1024*1024),"sample",5);fail();}
            catch(IOException expected) {assertEquals("observation_limit",expected.getMessage());}
        }
        assertEquals(4,status(root()).get("lastObservedTick").getAsInt());
    }
    @Test public void observedRobotAndRegionStillAdvanceStallAfterRecordingStops() throws Exception {
        RunnerObservations.StallClock clock=new RunnerObservations.StallClock();
        try(RunnerRecording recorder=new RunnerRecording(root(),1048576,"stop")) {
            assertTrue(recorder.record("x","initial",3));clock.observe(3,"robot",true);
            assertFalse(recorder.record(line(1048576),"sample",4));clock.observe(4,"robot",false);
            assertFalse(recorder.record("x","sample",9));clock.observe(9,"robot",true);
            assertEquals(9,clock.lastChangeTick());
            assertFalse(recorder.record("x","final",12));clock.observe(12,"robot",false);
        }
        assertEquals(12,status(root()).get("lastObservedTick").getAsInt());
        assertEquals(1,status(root()).get("recordsWritten").getAsInt());
    }
    @Test public void recordedFinalHasCoverageAfterOrderlyClose() throws Exception {
        RunnerRecording recorder=new RunnerRecording(root(),1048576,"fail");
        assertTrue(recorder.record("x","initial",3));
        assertTrue(recorder.record("z","final",7));
        recorder.close();
        assertTrue(status(root()).get("finalRecorded").getAsBoolean());
        assertEquals(7,status(root()).get("lastRecordedTick").getAsInt());
    }
    @Test public void partialStatusWriteCleansOnlyOwnedTemporaryFile() throws Exception {
        Path partial=folder.newFolder("partial-write").toPath();
        try {
            new RunnerRecording(partial,1048576,"stop",(source,target)->fail("move after failed write"),
                (stream,payload)->{stream.write(payload,0,2);throw new IOException("partial status write");});
            fail();
        } catch(IOException expected) {assertEquals("partial status write",expected.getMessage());}
        assertFalse(Files.exists(partial.resolve(".observations-status.json.tmp")));
        Files.delete(partial.resolve("observations.ndjson")); // constructor released writer

        Path collision=folder.newFolder("collision").toPath();
        Path existing=collision.resolve(".observations-status.json.tmp");
        Files.write(existing,"someone else's temp".getBytes(StandardCharsets.UTF_8));
        try {new RunnerRecording(collision,1048576,"stop");fail();}
        catch(FileAlreadyExistsException expected) {assertNotNull(expected);}
        assertEquals("someone else's temp",new String(Files.readAllBytes(existing),StandardCharsets.UTF_8));
        Files.delete(collision.resolve("observations.ndjson"));
    }
    @Test public void retryWaitsBrieflyAndInterruptPropagatesWithoutLeakingTemp() throws Exception {
        AtomicInteger attempts=new AtomicInteger();
        long start=System.nanoTime();
        try(RunnerRecording recorder=new RunnerRecording(root(),1048576,"stop",(source,target)->{
            if(attempts.incrementAndGet()<3) throw new IOException("sharing violation");
            Files.move(source,target,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        })) {assertEquals(3,attempts.get());}
        assertTrue("two bounded retry pauses expected",System.nanoTime()-start>=30_000_000L);
        Path interrupted=folder.newFolder("interrupted").toPath();
        try {
            try {new RunnerRecording(interrupted,1048576,"stop",(source,target)->{
                Thread.currentThread().interrupt(); // interrupt precisely after the temporary file was written
                throw new IOException("sharing violation");
            });fail();}
            catch(InterruptedIOException expected) {assertEquals("observation_status_interrupted",expected.getMessage());}
            assertTrue(Thread.currentThread().isInterrupted());
        } finally {Thread.interrupted();}
        assertFalse(Files.exists(interrupted.resolve(".observations-status.json.tmp")));
        Files.delete(interrupted.resolve("observations.ndjson"));
    }
    @Test public void atomicRetryAndPersistentFailureCleanTempAndWriter() throws Exception {
        AtomicInteger attempts=new AtomicInteger();
        RunnerRecording.Publisher retry=(source,target)->{
            if(attempts.incrementAndGet()<3) throw new IOException("sharing violation");
            Files.move(source,target,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        };
        try(RunnerRecording recorder=new RunnerRecording(root(),1048576,"stop",retry)) {
            assertTrue(recorder.record("x","initial",3));
        }
        assertTrue(attempts.get()>=4);
        Path failing=folder.newFolder("persistent").toPath();
        try {new RunnerRecording(failing,1048576,"stop",(source,target)->{throw new IOException("sharing violation");});fail();}
        catch(IOException expected) {assertTrue(expected.getMessage().contains("sharing violation"));}
        assertFalse(Files.exists(failing.resolve(".observations-status.json.tmp")));
        Files.delete(failing.resolve("observations.ndjson")); // constructor released writer
        Path closeFailure=folder.newFolder("close-failure").toPath();
        AtomicInteger moves=new AtomicInteger();
        RunnerRecording recorder=new RunnerRecording(closeFailure,1048576,"stop",(source,target)->{
            if(moves.incrementAndGet()>1) throw new IOException("sharing violation");
            Files.move(source,target,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        });
        assertTrue(recorder.record("x","initial",3));
        try {recorder.close();fail();}
        catch(IOException expected) {assertTrue(expected.getMessage().contains("sharing violation"));}
        assertFalse(Files.exists(closeFailure.resolve(".observations-status.json.tmp")));
        Files.delete(closeFailure.resolve("observations.ndjson"));
    }
}
