package ocelot.spike;

import com.google.gson.*;
import li.cil.oc.api.machine.Context;
import li.cil.oc.api.network.Packet;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** Opt-in, bounded host evidence. No guest filesystem, guest code, timers or threads. */
public final class HostCapture {
    private static final long LIMIT=64L*1024*1024;
    private static final int MESSAGE_LIMIT=1024*1024, ASSEMBLIES=64;
    private static BufferedWriter writer;
    private static long bytes, sequence;
    private static boolean stopped;
    private static long frames, rpcCalls, decodeErrors, evictions;
    private static final LinkedHashMap<String,Fragments> pending=new LinkedHashMap<>();
    private HostCapture() {}

    public static void sent(Object card, Packet packet, Context context) {
        if(!Boolean.getBoolean("robotspike.hostCapture")) return;
        capture("send",card,packet,context,0,System.nanoTime(),Trace.tick);
    }
    public static void accepted(boolean accepted, Object card, Packet packet, double distance) {
        if(!accepted || !Boolean.getBoolean("robotspike.hostCapture")) return;
        capture("receiveAccepted",card,packet,null,distance,System.nanoTime(),Trace.tick);
    }
    private static synchronized void capture(String direction,Object card,Packet packet,Context context,double distance,long boundaryNanos,long tick) {
        if(stopped) return;
        try {
            JsonObject event=new JsonObject(); event.addProperty("kind","modemFrame");
            event.addProperty("hostNanos",boundaryNanos); event.addProperty("tick",tick);
            event.addProperty("direction",direction); event.addProperty("source",packet.source());
            event.addProperty("destination",packet.destination()); event.addProperty("port",packet.port());
            event.addProperty("payloadSize",packet.size()); event.addProperty("distance",distance);
            event.addProperty("computer",context==null?null:context.node().address());
            if(context!=null && context.getClass().getName().equals("li.cil.oc.server.machine.Machine")) {
                // Read fields only: upTime() itself mutates old-save migration state.
                java.lang.reflect.Field uptime=context.getClass().getDeclaredField("uptime"); uptime.setAccessible(true);
                long ticks=uptime.getLong(context);
                if(ticks<0) {
                    java.lang.reflect.Field world=context.getClass().getDeclaredField("worldTime"); world.setAccessible(true);
                    ticks+=world.getLong(context);
                }
                event.addProperty("computerUptimeSeconds",ticks/20.0);
                event.addProperty("computerUptimeSampleHostNanos",System.nanoTime());
                event.addProperty("computerUptimeClock","OC Machine uptime ticks / 20; send-boundary sample");
                if(Boolean.getBoolean("robotspike.realflow")) {
                    event.add("nativePower",RunnerMachineEvidence.power((li.cil.oc.api.network.Connector)context.node()));
                    try {event.add("nativeMemory",RunnerMachineEvidence.memory((li.cil.oc.api.machine.Machine)context));}
                    catch(ReflectiveOperationException e) {event.addProperty("nativeMemoryError",e.toString());}
                }
            }
            Object node=card.getClass().getMethod("node").invoke(card);
            String modem=((li.cil.oc.api.network.Node)node).address();
            event.addProperty("localModem",modem);
            li.cil.oc.api.network.EnvironmentHost host=(li.cil.oc.api.network.EnvironmentHost)card.getClass().getMethod("host").invoke(card);
            event.addProperty("hostClass",host.getClass().getName());
            event.addProperty("xPosition",host.xPosition()); event.addProperty("yPosition",host.yPosition());
            event.addProperty("zPosition",host.zPosition());
            Object[] data=packet.data(); JsonArray parts=new JsonArray();
            for(Object part:data) {
                if(part==null) parts.add(JsonNull.INSTANCE);
                else if(part instanceof byte[]) {
                    JsonObject binary=new JsonObject(); binary.addProperty("base64",Base64.getEncoder().encodeToString((byte[])part)); parts.add(binary);
                } else if(part instanceof Number) parts.add(new JsonPrimitive((Number)part));
                else if(part instanceof Boolean) parts.add(new JsonPrimitive((Boolean)part));
                else if(part instanceof String) parts.add(new JsonPrimitive((String)part));
                else throw new IllegalArgumentException("unsupported modem payload "+part.getClass());
            }
            event.add("parts",parts);
            decode(event,data,direction+"|"+modem+"|"+packet.source()+"|"+packet.destination()+"|"+packet.port());
            frames++;
            write(event);
        } catch(Exception error) { stop("captureError: "+error); }
    }
    static String text(Object value) {
        return value instanceof byte[]?new String((byte[])value,StandardCharsets.UTF_8):value instanceof String?(String)value:null;
    }
    static void decode(JsonObject event,Object[] data,String scope) {
        if(data.length>=4 && "report".equals(text(data[1]))) {
            event.addProperty("tripId",String.valueOf(data[2]));
            try { event.add("droneReport",HostLuaTable.parse(text(data[3]))); }
            catch(RuntimeException e) { decodeErrors++; event.addProperty("decodeError","drone report: "+e.getMessage()); }
        }
        if(data.length<2 || text(data[1])==null) return;
        String[] header=text(data[1]).split(",",-1);
        if(header.length!=4 && header.length!=6) return;
        if(!Arrays.asList("c","a","d","s","m").contains(header[3])) return;
        JsonObject tnet=new JsonObject();
        tnet.addProperty("system",header[0]); tnet.addProperty("connection",header[1]);
        tnet.addProperty("messageId",header[2]); tnet.addProperty("type",header[3]); event.add("tnet",tnet);
        if(!header[3].equals("m") || data.length<4 || text(data[3])==null) return;
        String serialized=text(data[3]);
        try {
            if(header.length==6) {
                int index=Integer.parseInt(header[4]), total=Integer.parseInt(header[5]);
                tnet.addProperty("fragment",index); tnet.addProperty("fragments",total);
                if(total<1 || total>256 || index<1 || index>total) throw new IllegalArgumentException("fragment bound");
                String key=scope+"|"+header[0]+"|"+header[1]+"|"+header[2];
                Fragments f=pending.get(key);
                if(f==null) {
                    if(pending.size()==ASSEMBLIES) {
                        String evicted=pending.keySet().iterator().next(); pending.remove(evicted); evictions++;
                        event.addProperty("assemblyEvicted",evicted);
                    }
                    f=new Fragments(total); pending.put(key,f);
                }
                if(f.parts.length!=total) { pending.remove(key); throw new IllegalArgumentException("fragment total changed"); }
                byte[] fragment=data[3] instanceof byte[]?(byte[])data[3]:serialized.getBytes(StandardCharsets.UTF_8);
                if(f.parts[index-1]!=null && !Arrays.equals(f.parts[index-1],fragment)) {
                    pending.remove(key); throw new IllegalArgumentException("conflicting fragment");
                }
                if(f.parts[index-1]==null) { f.parts[index-1]=fragment.clone(); f.size+=fragment.length; f.count++; }
                if(f.size>MESSAGE_LIMIT) { pending.remove(key); throw new IllegalArgumentException("message bound"); }
                if(f.count!=total) { tnet.addProperty("decodeStatus","incomplete"); return; }
                ByteArrayOutputStream all=new ByteArrayOutputStream(f.size);
                for(byte[] part:f.parts) all.write(part,0,part.length);
                serialized=new String(all.toByteArray(),StandardCharsets.UTF_8); pending.remove(key);
            }
            JsonElement parsed=HostLuaTable.parse(serialized); event.add("tnetMessage",parsed);
            tnet.addProperty("decodeStatus","complete");
            if(parsed.isJsonObject()) {
                JsonObject message=parsed.getAsJsonObject();
                if(message.has("msg") && "rpc".equals(message.get("msg").getAsString()) && message.has("args")) {
                    JsonObject args=message.getAsJsonObject("args");
                    if(args.has("1")) event.add("rpcType",args.get("1"));
                    if(args.has("1") && "rpc_call".equals(args.get("1").getAsString()) && args.has("2") && args.has("3")) {
                        event.add("rpcFunction",args.get("2")); event.add("rpcCallId",args.get("3"));
                        rpcCalls++;
                    }
                }
            }
        } catch(RuntimeException e) { decodeErrors++; tnet.addProperty("decodeStatus","unsupportedOrInvalid"); event.addProperty("decodeError",e.getMessage()); }
    }
    private static final class Fragments {
        final byte[][] parts; int count,size; Fragments(int total) { parts=new byte[total][]; }
    }
    private static void write(JsonObject event) throws IOException {
        if(writer==null) {
            String configured=System.getProperty("robotspike.hostCaptureFile");
            if(configured==null) throw new IOException("robotspike.hostCaptureFile must be an absolute host path");
            Path path=Paths.get(configured);
            if(!path.isAbsolute()) throw new IOException("capture path must be absolute");
            writer=Files.newBufferedWriter(path,StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);
            // Only JVM shutdown, not a running thread or polling loop. Flush an explicit coverage summary.
            Runtime.getRuntime().addShutdownHook(new Thread(HostCapture::finish,"host-capture-close"));
        }
        event.addProperty("sequence",++sequence); event.addProperty("thread",Thread.currentThread().getName());
        String line=event.toString(); long size=line.getBytes(StandardCharsets.UTF_8).length+1;
        if(bytes+size>LIMIT-4096) { stop("byteLimit"); return; }
        writer.write(line); writer.newLine(); writer.flush(); bytes+=size;
    }
    private static void stop(String reason) {
        stopped=true; System.err.println("HOST_CAPTURE_STOPPED "+reason);
        if(writer!=null) try {
            JsonObject end=summary(reason); end.addProperty("kind","captureStopped");
            writer.write(end.toString()); writer.newLine(); writer.close();
        } catch(IOException ignored) {} finally { writer=null; pending.clear(); }
    }
    static synchronized void finish() {
        if(writer==null) return;
        try { writer.write(summary("jvmShutdown").toString()); writer.newLine(); writer.close(); }
        catch(IOException e) { System.err.println("HOST_CAPTURE_CLOSE_ERROR "+e); }
        finally { writer=null; stopped=true; pending.clear(); }
    }
    static JsonObject summary(String reason) {
        JsonObject end=new JsonObject(); end.addProperty("kind","captureSummary"); end.addProperty("reason",reason);
        end.addProperty("frameObservations",frames); end.addProperty("rpcCallObservations",rpcCalls);
        end.addProperty("decodeErrors",decodeErrors); end.addProperty("assemblyEvictions",evictions);
        end.addProperty("unfinishedAssemblies",pending.size());
        end.addProperty("decodeCoverageComplete",decodeErrors==0 && evictions==0 && pending.isEmpty());
        end.addProperty("streamComplete",reason.equals("jvmShutdown"));
        return end;
    }
    static synchronized void resetForTest() {
        if(writer!=null) try { writer.close(); } catch(IOException e) { throw new UncheckedIOException(e); }
        writer=null; bytes=0; sequence=0; frames=0; rpcCalls=0; decodeErrors=0; evictions=0; stopped=false; pending.clear();
    }
}
