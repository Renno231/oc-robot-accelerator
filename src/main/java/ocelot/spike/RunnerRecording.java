package ocelot.spike;

import com.google.gson.JsonObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;

/** Complete UTF-8 observation prefix and bounded, atomically published coverage checkpoint. */
final class RunnerRecording implements Closeable {
    interface Publisher {void move(Path source,Path target) throws IOException;}
    interface StatusWriter {void write(OutputStream stream,byte[] payload) throws IOException;}
    private static final int STATUS_LIMIT=64*1024, LINE_LIMIT=8*1024*1024;
    private static final long RETRY_DELAY_MILLIS=25;
    private final Path root;
    private final OutputStream output;
    private final Publisher publisher;
    private final StatusWriter statusWriter;
    private final int maxBytes;
    private final String policy;
    private long bytesWritten, recordsWritten, lastRecordedTick=-1, lastObservedTick=-1;
    private boolean stopped, finalRecorded, closed, failed;

    RunnerRecording(Path root,int maxBytes,String policy) throws IOException {
        this(root,maxBytes,policy,(source,target)->Files.move(source,target,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING));
    }
    RunnerRecording(Path root,int maxBytes,String policy,Publisher publisher) throws IOException {
        this(root,maxBytes,policy,publisher,(stream,payload)->stream.write(payload));
    }
    RunnerRecording(Path root,int maxBytes,String policy,Publisher publisher,StatusWriter statusWriter) throws IOException {
        if(maxBytes<1048576 || maxBytes>33554432 || !(policy.equals("stop") || policy.equals("fail")))
            throw new IllegalArgumentException("recording policy");
        this.root=root;this.maxBytes=maxBytes;this.policy=policy;this.publisher=publisher;this.statusWriter=statusWriter;
        output=Files.newOutputStream(root.resolve("observations.ndjson"),StandardOpenOption.CREATE_NEW);
        try {publish();}
        catch(IOException | RuntimeException error) {
            try {output.close();} catch(IOException close) {error.addSuppressed(close);}
            throw error;
        }
    }
    /** False means the prefix is now permanently stopped; sampling must still continue. */
    boolean record(String line,String kind,long tick) throws IOException {
        if(closed || failed) throw new IOException("recording_closed");
        try {
            byte[] wire=RunnerObservations.wireLine(line);
            if(tick<0 || wire.length>LINE_LIMIT) throw new IOException("observation_limit");
            if(stopped) {lastObservedTick=tick;return false;}
            if(bytesWritten+wire.length>maxBytes) {
                if(policy.equals("fail") || recordsWritten==0 || kind.equals("initial")) throw new IOException("observation_limit");
                stopped=true;lastObservedTick=tick;publish();return false;
            }
            output.write(wire);output.flush();
            bytesWritten+=wire.length;recordsWritten++;lastRecordedTick=tick;lastObservedTick=tick;
            if(kind.equals("final")) finalRecorded=true;
            return true;
        } catch(IOException error) {failed=true;throw error;}
    }
    long lastObservedTick() {return lastObservedTick;}
    long recordsWritten() {return recordsWritten;}
    long bytesWritten() {return bytesWritten;}
    JsonObject coverage() {
        JsonObject status=new JsonObject();
        status.addProperty("schemaVersion",1);status.addProperty("policy",policy);status.addProperty("maxBytes",maxBytes);
        status.addProperty("bytesWritten",bytesWritten);status.addProperty("recordsWritten",recordsWritten);
        if(lastRecordedTick<0) status.add("lastRecordedTick",com.google.gson.JsonNull.INSTANCE);
        else status.addProperty("lastRecordedTick",lastRecordedTick);
        if(lastObservedTick<0) status.add("lastObservedTick",com.google.gson.JsonNull.INSTANCE);
        else status.addProperty("lastObservedTick",lastObservedTick);
        status.addProperty("recordingStopped",stopped);
        if(stopped) status.addProperty("stopReason","byte_limit");
        else status.add("stopReason",com.google.gson.JsonNull.INSTANCE);
        status.addProperty("finalRecorded",finalRecorded);
        return status;
    }
    private void publish() throws IOException {
        byte[] payload=coverage().toString().getBytes(StandardCharsets.UTF_8);
        if(payload.length>STATUS_LIMIT) throw new IOException("observation_status_limit");
        Path temp=root.resolve(".observations-status.json.tmp"),target=root.resolve("observations-status.json");
        boolean owned=false;
        try {
            try(OutputStream stream=Files.newOutputStream(temp,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE)) {
                owned=true; // only the successfully created file belongs to this publication
                statusWriter.write(stream,payload);
            }
            IOException failure=null;
            for(int attempt=0;attempt<3;attempt++) {
                try {publisher.move(temp,target);return;}
                catch(IOException error) {
                    failure=error;
                    if(attempt<2) {
                        try {Thread.sleep(RETRY_DELAY_MILLIS);}
                        catch(InterruptedException interrupted) {
                            Thread.currentThread().interrupt();
                            InterruptedIOException aborted=new InterruptedIOException("observation_status_interrupted");
                            aborted.initCause(interrupted);
                            aborted.addSuppressed(error);
                            throw aborted;
                        }
                    }
                }
            }
            throw failure;
        } finally {if(owned) Files.deleteIfExists(temp);}
    }
    @Override public void close() throws IOException {
        if(closed) return;
        closed=true;
        IOException failure=null;
        try {output.close();} catch(IOException error) {failure=error;}
        try {publish();} catch(IOException error) {if(failure==null) failure=error; else failure.addSuppressed(error);}
        if(failure!=null) throw failure;
    }
}
