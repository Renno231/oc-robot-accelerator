package ocelot.spike;

import com.google.gson.*;
import org.junit.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.lang.reflect.*;
import li.cil.oc.api.network.*;
import li.cil.oc.api.machine.Context;
import static org.junit.Assert.*;

public class HostCaptureTest {
    private String flag,path;
    @Before public void before() { flag=System.getProperty("robotspike.hostCapture"); path=System.getProperty("robotspike.hostCaptureFile"); HostCapture.resetForTest(); }
    @After public void after() { HostCapture.resetForTest(); restore("robotspike.hostCapture",flag); restore("robotspike.hostCaptureFile",path); }
    private void restore(String key,String value) { if(value==null) System.clearProperty(key); else System.setProperty(key,value); }
    private JsonObject decode(Object[] data,String scope) { JsonObject event=new JsonObject(); HostCapture.decode(event,data,scope); return event; }
    @Test public void parsesCurrentOpenOsSerializationWithoutExecutingCode() {
        JsonObject p=HostLuaTable.parse("{msg=\"rpc\",args={\"rpc_call\",\"craft\",\"2\",{true,nil,[\"quote\"]=\"x\\034y\"},n=5}}").getAsJsonObject();
        assertEquals("rpc",p.get("msg").getAsString());
        assertTrue(p.getAsJsonObject("args").getAsJsonObject("4").get("1").getAsBoolean());
    }
    @Test(expected=IllegalArgumentException.class) public void rejectsExecutableSerialization() { HostLuaTable.parse("(function() os.exit() end)()"); }
    @Test public void completeRpcOnlyAfterAllFragmentsInOrderOrOutOfOrder() {
        String a="{msg=\"rpc\",args={\"rpc_call\",", b="\"status\",\"7\",{},n=5}}";
        JsonObject first=decode(new Object[]{"wake","api_client,c1,1,m,2,2","rpc",b},"send|robotA");
        assertFalse(first.has("rpcFunction")); assertEquals("incomplete",first.getAsJsonObject("tnet").get("decodeStatus").getAsString());
        decode(new Object[]{"wake","api_client,c1,1,m,2,2","rpc",b},"send|robotA");
        JsonObject last=decode(new Object[]{"wake","api_client,c1,1,m,1,2","rpc",a},"send|robotA");
        assertEquals("status",last.get("rpcFunction").getAsString()); assertEquals("7",last.get("rpcCallId").getAsString());
        assertEquals(0,HostCapture.summary("test").get("unfinishedAssemblies").getAsInt());
    }
    @Test public void endpointAndDirectionIsolateFragments() {
        decode(new Object[]{"w","api_client,c,1,m,1,2","rpc","{msg=\"rpc\","},"send|a");
        assertFalse(decode(new Object[]{"w","api_client,c,1,m,2,2","rpc","args={}}"},"receive|a").has("tnetMessage"));
        assertEquals(2,HostCapture.summary("test").get("unfinishedAssemblies").getAsInt());
    }
    @Test public void byteFragmentsReassembleBeforeUtf8Decoding() {
        byte[] wire="{msg=\"rpc\",args={\"rpc_call\",\"café\",\"1\",{}}}".getBytes(StandardCharsets.UTF_8);
        int split=0; while(wire[split]!=(byte)0xc3) split++; split++;
        decode(new Object[]{"w","api_client,c,1,m,1,2","rpc",java.util.Arrays.copyOfRange(wire,0,split)},"x");
        JsonObject last=decode(new Object[]{"w","api_client,c,1,m,2,2","rpc",java.util.Arrays.copyOfRange(wire,split,wire.length)},"x");
        assertEquals("café",last.get("rpcFunction").getAsString());
    }
    @Test public void malformedConflictAndEvictionAreVisible() {
        Object[] a={"w","api_client,c,1,m,1,2","rpc","abc"}; decode(a,"x");
        a[3]="xyz"; assertTrue(decode(a,"x").has("decodeError"));
        for(int i=0;i<65;i++) decode(new Object[]{"w","api_client,c,"+i+",m,1,2","rpc","{"},"x");
        JsonObject summary=HostCapture.summary("test"); assertEquals(1,summary.get("assemblyEvictions").getAsInt());
        assertFalse(summary.get("decodeCoverageComplete").getAsBoolean());
    }
    @Test public void droneReportIncludesResultButDoesNotInventCompletion() {
        JsonObject result=decode(new Object[]{"token","report",42.0,"{[\"state\"]=\"done\",[\"moved\"]=12,}"},"drone");
        assertEquals("done",result.getAsJsonObject("droneReport").get("state").getAsString());
        assertFalse(result.has("tripFinished"));
    }
    @Test public void nativeSequence709DroneReportInfIsTypedAndRawVisible() {
        // SCALE12-r2 exact report payload, sequence 709 (raw wire bytes remain in capture parts).
        String base64="e1siY2FyZ29TbG90cyJdPTQsWyJmcmVlTWVtb3J5Il09OTU5NTUsWyJzdXJ2ZXkiXT1mYWxzZSxbInBvc2l0aW9uIl09e1sieSJdPTY1LFsieCJdPS0yLFsieiJdPTIsfSxbInN0YXRlIl09InJlYWR5IixbImVuZXJneSJdPWluZixbImhlbGQiXT0wLH0=";
        JsonObject result=decode(new Object[]{"3126d9","report",0,java.util.Base64.getDecoder().decode(base64)},"native709");
        assertFalse(result.has("decodeError"));
        JsonObject energy=result.getAsJsonObject("droneReport").getAsJsonObject("energy");
        assertEquals("oc.nonfinite",energy.get("$type").getAsString());
        assertEquals("inf",energy.get("raw").getAsString());
        assertEquals("positiveInfinity",energy.get("value").getAsString());
        assertFalse(result.getAsJsonObject("droneReport").get("energy").isJsonPrimitive());
        assertTrue(HostCapture.summary("test").get("decodeCoverageComplete").getAsBoolean());
    }
    @Test public void nonfiniteScalarTokensRemainTypedNotNumbersOrQuotedStrings() {
        JsonObject values=HostLuaTable.parse("{inf,-inf,nan,\"inf\",42}").getAsJsonObject();
        assertEquals("negativeInfinity",values.getAsJsonObject("2").get("value").getAsString());
        assertEquals("notANumber",values.getAsJsonObject("3").get("value").getAsString());
        assertEquals("inf",values.get("4").getAsString()); assertEquals(42,values.get("5").getAsInt());
        new JsonParser().parse(values.toString()); // Valid JSON, no bare Infinity/NaN.
    }
    @Test public void nonfiniteAllowanceNeverEvaluatesExpressions() {
        for(String invalid:new String[]{"infinity","Inf","-nan","math.huge","0/0","inf+1","inf()","nan or os.exit()"}) {
            try { HostLuaTable.parse("{energy="+invalid+"}"); fail(invalid); }
            catch(IllegalArgumentException expected) {}
        }
    }
    public static class Card {
        public Node node() { return proxy(Node.class,(p,m,a)->m.getName().equals("address")?"modem-robot":null); }
        public EnvironmentHost host() { return proxy(EnvironmentHost.class,(p,m,a)->m.getName().endsWith("Position")?Double.valueOf(12):null); }
    }
    @SuppressWarnings("unchecked") private static <T> T proxy(Class<T> type,InvocationHandler handler) {
        return (T)Proxy.newProxyInstance(type.getClassLoader(),new Class<?>[]{type},handler);
    }
    private Packet packet() { return proxy(Packet.class,(p,m,a)-> {
        switch(m.getName()) {
            case "source": return "modem-robot"; case "destination": return "mes-modem";
            case "port": return 5990; case "size": return 4;
            case "data": return new Object[]{new byte[]{0,(byte)255},"hello"}; default: return null;
        }
    }); }
    private Context context() { return proxy(Context.class,(p,m,a)->new Card().node()); }
    @Test public void flagOffCreatesNoFileAndRejectedPacketsAreIgnored() throws Exception {
        Path target=Files.createTempDirectory("host-off").resolve("capture.ndjson");
        System.clearProperty("robotspike.hostCapture"); System.setProperty("robotspike.hostCaptureFile",target.toString());
        HostCapture.sent(new Card(),packet(),context()); assertFalse(Files.exists(target));
        System.setProperty("robotspike.hostCapture","true"); HostCapture.accepted(false,new Card(),packet(),0); assertFalse(Files.exists(target));
    }
    @Test public void artifactOutsideGuestKeepsExactBytesAndSummary() throws Exception {
        Path target=Files.createTempDirectory("host-on").resolve("capture.ndjson");
        System.setProperty("robotspike.hostCapture","true"); System.setProperty("robotspike.hostCaptureFile",target.toString());
        HostCapture.sent(new Card(),packet(),context()); HostCapture.finish();
        java.util.List<String> lines=Files.readAllLines(target,StandardCharsets.UTF_8); assertEquals(2,lines.size());
        JsonObject event=new JsonParser().parse(lines.get(0)).getAsJsonObject();
        assertEquals("AP8=",event.getAsJsonArray("parts").get(0).getAsJsonObject().get("base64").getAsString());
        assertEquals("modem-robot",event.get("source").getAsString());
        assertTrue(new JsonParser().parse(lines.get(1)).getAsJsonObject().get("streamComplete").getAsBoolean());
    }
    @Test public void capStopsExplicitlyWithoutThrowingIntoOc() throws Exception {
        Path target=Files.createTempDirectory("host-cap").resolve("capture.ndjson");
        System.setProperty("robotspike.hostCapture","true"); System.setProperty("robotspike.hostCaptureFile",target.toString());
        HostCapture.sent(new Card(),packet(),context());
        Field bytes=HostCapture.class.getDeclaredField("bytes"); bytes.setAccessible(true); bytes.setLong(null,64L*1024*1024-4096);
        HostCapture.sent(new Card(),packet(),context());
        assertTrue(new String(Files.readAllBytes(target),StandardCharsets.UTF_8).contains("byteLimit"));
    }
    @Test public void existingArtifactsAreNeverOverwritten() throws Exception {
        Path target=Files.createTempFile("host-existing",".ndjson"); Files.write(target,"sentinel".getBytes(StandardCharsets.UTF_8));
        System.setProperty("robotspike.hostCapture","true"); System.setProperty("robotspike.hostCaptureFile",target.toString());
        HostCapture.sent(new Card(),packet(),context());
        assertEquals("sentinel",new String(Files.readAllBytes(target),StandardCharsets.UTF_8));
    }
}
