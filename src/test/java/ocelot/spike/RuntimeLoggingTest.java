package ocelot.spike;

import com.google.gson.JsonObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class RuntimeLoggingTest {
    private static final String PROFILE="mc1.12.2-forge2860-oc1.8.9a-log4j2.25.5-v1";
    private static final String API="libraries/org/apache/logging/log4j/log4j-api/2.15.0/log4j-api-2.15.0.jar";
    private static final String CORE="libraries/org/apache/logging/log4j/log4j-core/2.15.0/log4j-core-2.15.0.jar";
    private static final String A="org.apache.logging.log4j.LogManager", C="org.apache.logging.log4j.core.LoggerContext";
    private static String hash(byte[] bytes) throws Exception {
        byte[] digest=MessageDigest.getInstance("SHA-256").digest(bytes);
        StringBuilder text=new StringBuilder();for(byte b:digest) text.append(String.format("%02x",b&255));return text.toString();
    }
    private static void rejects(Runnable action) {
        try {action.run();fail("expected rejection");}catch(IllegalArgumentException | IllegalStateException expected) {}
    }
    @Test public void profileIsExactAndAbsentPropertyIsHistoricalNoOp() throws Exception {
        assertFalse(RuntimeLogging.enabled(null));
        assertTrue(RuntimeLogging.enabled(PROFILE));
        rejects(()->RuntimeLogging.enabled(""));
        rejects(()->RuntimeLogging.enabled("unknown"));
        Path root=Files.createTempDirectory("logging-noop");
        RuntimeLogging.verify(root,null);
        assertFalse(Files.exists(root.resolve("runtime-logging.json")));
    }
    @Test public void sourceVersionHashAndClassNameAreExact() throws Exception {
        Path root=Files.createTempDirectory("logging-policy");
        Path file=root.resolve(API);Files.createDirectories(file.getParent());
        byte[] bytes="fixture jar bytes".getBytes(StandardCharsets.UTF_8);Files.write(file,bytes);
        String digest=hash(bytes);
        JsonObject good=RuntimeLogging.checkEvidence(root,A,file.toUri().toURL().toString(),"2.25.5",API,digest);
        assertEquals(API,good.get("source").getAsString());
        assertEquals("2.25.5",good.get("version").getAsString());
        assertEquals(digest,good.get("sha256").getAsString());
        rejects(()->{try {RuntimeLogging.checkEvidence(root,A,file.toUri().toURL().toString(),"2.15.0",API,digest);}catch(Exception e){throw new IllegalStateException(e);}});
        rejects(()->{try {RuntimeLogging.checkEvidence(root,A,file.toUri().toURL().toString(),"2.25.5",API,"0000");}catch(Exception e){throw new IllegalStateException(e);}});
        Path other=root.resolve(CORE);Files.createDirectories(other.getParent());Files.write(other,bytes);
        rejects(()->{try {RuntimeLogging.checkEvidence(root,A,other.toUri().toURL().toString(),"2.25.5",API,digest);}catch(Exception e){throw new IllegalStateException(e);}});
        rejects(()->{try {RuntimeLogging.checkEvidence(root,"other",file.toUri().toURL().toString(),"2.25.5",API,digest);}catch(Exception e){throw new IllegalStateException(e);}});
    }
    @Test public void proofIsBoundedAndNeverOverwritesUnownedFile() throws Exception {
        Path root=Files.createTempDirectory("logging-proof");
        Path proof=root.resolve("runtime-logging.json");Files.write(proof,"owned".getBytes(StandardCharsets.UTF_8));
        try {RuntimeLogging.writeProof(root,new byte[]{1});fail("must reject collision");}catch(FileAlreadyExistsException expected) {}
        assertEquals("owned",new String(Files.readAllBytes(proof),StandardCharsets.UTF_8));
        Files.delete(proof);
        try {RuntimeLogging.writeProof(root,new byte[65537]);fail("must reject size");}catch(java.io.IOException expected) {}
        assertFalse(Files.exists(proof));
        RuntimeLogging.writeProof(root,"{}".getBytes(StandardCharsets.UTF_8));
        assertEquals("{}",new String(Files.readAllBytes(proof),StandardCharsets.UTF_8));
    }
}
