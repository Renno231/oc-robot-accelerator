package ocelot.spike;

import com.google.gson.JsonObject;
import java.io.*;
import java.lang.reflect.Method;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.util.*;

/** Startup proof of the actual Log4j classes selected by the live runtime classloader. */
final class RuntimeLogging {
    private static final String PROFILE="mc1.12.2-forge2860-oc1.8.9a-log4j2.25.5-v1";
    private static final String API="libraries/org/apache/logging/log4j/log4j-api/2.15.0/log4j-api-2.15.0.jar";
    private static final String CORE="libraries/org/apache/logging/log4j/log4j-core/2.15.0/log4j-core-2.15.0.jar";
    private static final String API_HASH="64777f73ea0b3104c04eb82befbdccc30a425a19e83ad06cb2f93aa303511863";
    private static final String CORE_HASH="050c4f85deb48b055e9c041ac39043fbb79ce477841a11a1eb2969c86c6a0072";
    private RuntimeLogging() {}

    static boolean enabled(String profile) {
        if(profile==null) return false;
        if(!PROFILE.equals(profile)) throw new IllegalArgumentException("runtime_logging_profile");
        return true;
    }
    static void verify(Path root,String profile) throws IOException {
        if(!enabled(profile)) return;
        try {
            Class<?> manager=Class.forName("org.apache.logging.log4j.LogManager");
            Class<?> logger=Class.forName("org.apache.logging.log4j.Logger");
            Class<?> coreContext=Class.forName("org.apache.logging.log4j.core.LoggerContext");
            Class<?> configuration=Class.forName("org.apache.logging.log4j.core.config.Configuration");
            Class<?> jndi=Class.forName("org.apache.logging.log4j.core.lookup.JndiLookup");
            Object factory=manager.getMethod("getFactory").invoke(null);
            Object context=manager.getMethod("getContext",boolean.class).invoke(null,false);
            if(factory==null || context==null || !coreContext.isInstance(context)
                    || !factory.getClass().getName().startsWith("org.apache.logging.log4j.core."))
                throw new IllegalStateException("runtime_logging_implementation");
            JsonObject classes=new JsonObject();
            for(Class<?> type:new Class<?>[]{manager,logger,coreContext,configuration,jndi, factory.getClass(),context.getClass()}) {
                String name=type.getName();
                boolean api=name.equals(manager.getName()) || name.equals(logger.getName());
                String target=api?API:CORE,hash=api?API_HASH:CORE_HASH;
                if(classes.has(name)) continue;
                if(type.getProtectionDomain()==null || type.getProtectionDomain().getCodeSource()==null)
                    throw new IllegalStateException("runtime_logging_source");
                URL source=type.getProtectionDomain().getCodeSource().getLocation();
                Package pkg=type.getPackage();
                classes.add(name,checkEvidence(root,name,source.toString(),pkg==null?null:pkg.getImplementationVersion(),target,hash));
            }
            JsonObject proof=new JsonObject();proof.addProperty("schemaVersion",1);
            proof.addProperty("profileId",profile);proof.add("classes",classes);
            proof.addProperty("contextClass",context.getClass().getName());
            proof.addProperty("factoryClass",factory.getClass().getName());
            writeProof(root,proof.toString().getBytes(StandardCharsets.UTF_8));
        }catch(ReflectiveOperationException | java.net.URISyntaxException | GeneralSecurityException error) {
            throw new IOException("runtime_logging_verification",error);
        }
    }
    static JsonObject checkEvidence(Path root,String name,String source,String version,String target,String expectedHash)
            throws IOException,java.net.URISyntaxException,GeneralSecurityException {
        if(!name.startsWith("org.apache.logging.log4j.") ||
                !(target.equals(API) && (name.equals("org.apache.logging.log4j.LogManager") || name.equals("org.apache.logging.log4j.Logger"))
                  || target.equals(CORE) && name.startsWith("org.apache.logging.log4j.core.")))
            throw new IllegalArgumentException("runtime_logging_class");
        if(!"2.25.5".equals(version)) throw new IllegalStateException("runtime_logging_version:"+name);
        Path expected=root.resolve(target).toAbsolutePath().normalize();
        Path actual=Paths.get(new URL(source).toURI()).toAbsolutePath().normalize();
        if(Files.isSymbolicLink(expected) || !actual.equals(expected) || !Files.isRegularFile(expected)
                || !expected.toRealPath().equals(expected)) throw new IllegalStateException("runtime_logging_source:"+name);
        String hash=hash(expected);
        if(!hash.equals(expectedHash)) throw new IllegalStateException("runtime_logging_hash:"+name);
        JsonObject entry=new JsonObject();entry.addProperty("source",target);
        entry.addProperty("version",version);entry.addProperty("sha256",hash);return entry;
    }
    private static String hash(Path file) throws IOException,GeneralSecurityException {
        if(Files.size(file)>8*1024*1024) throw new IOException("runtime_logging_jar_bound");
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        try(InputStream in=Files.newInputStream(file)) {
            byte[] buf=new byte[8192];int n;long total=0;
            while((n=in.read(buf))!=-1) {
                total+=n;if(total>8*1024*1024) throw new IOException("runtime_logging_jar_bound");
                digest.update(buf,0,n);
            }
        }
        StringBuilder result=new StringBuilder();for(byte b:digest.digest()) result.append(String.format(Locale.ROOT,"%02x",b&255));
        return result.toString();
    }
    static void writeProof(Path root,byte[] bytes) throws IOException {
        if(bytes.length>64*1024) throw new IOException("runtime_logging_proof_bound");
        Path target=root.resolve("runtime-logging.json");boolean owned=false;
        try {
            try(OutputStream out=Files.newOutputStream(target,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE)) {
                owned=true;out.write(bytes);
            }
        }catch(IOException failure) {
            if(owned) try {Files.deleteIfExists(target);}catch(IOException cleanup) {failure.addSuppressed(cleanup);}
            throw failure;
        }
    }
}
