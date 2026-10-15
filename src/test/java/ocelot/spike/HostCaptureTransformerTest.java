package ocelot.spike;

import org.junit.Test;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import org.objectweb.asm.tree.analysis.*;
import java.util.jar.*;
import java.io.*;
import static org.junit.Assert.*;

public class HostCaptureTransformerTest {
    @Test public void pinnedOcPacketStacksVerifyAndOffIsByteIdentical() throws Exception {
        byte[] original;
        try(JarFile jar=new JarFile(".cache/OpenComputers-1.8.9a.jar")) {
            try(InputStream in=jar.getInputStream(jar.getJarEntry("li/cil/oc/server/component/NetworkCard.class"))) {
                ByteArrayOutputStream out=new ByteArrayOutputStream(); byte[] b=new byte[8192]; int n;
                while((n=in.read(b))!=-1) out.write(b,0,n); original=out.toByteArray();
            }
        }
        String before=System.getProperty("robotspike.hostCapture");
        try {
            System.clearProperty("robotspike.hostCapture");
            // With capture off, this target must not even be rewritten.
            byte[] off=new PacingTransformer().transform("x","li.cil.oc.server.component.NetworkCard",original);
            assertArrayEquals(original,off);
            ClassNode a=new ClassNode(); new ClassReader(off).accept(a,0);
            for(MethodNode m:a.methods) for(AbstractInsnNode i:m.instructions.toArray())
                if(i instanceof MethodInsnNode) assertNotEquals("ocelot/spike/HostCapture",((MethodInsnNode)i).owner);
            System.setProperty("robotspike.hostCapture","true");
            ClassNode node=new ClassNode();
            new ClassReader(new PacingTransformer().transform("x","li.cil.oc.server.component.NetworkCard",original)).accept(node,0);
            int sent=0,accepted=0;
            for(MethodNode m:node.methods) {
                new Analyzer<BasicValue>(new BasicVerifier()).analyze(node.name,m);
                for(AbstractInsnNode i:m.instructions.toArray()) if(i instanceof MethodInsnNode) {
                    MethodInsnNode call=(MethodInsnNode)i;
                    if(call.owner.equals("ocelot/spike/HostCapture")) {
                        if(call.name.equals("sent")) sent++; if(call.name.equals("accepted")) accepted++;
                    }
                }
            }
            assertEquals(2,sent); assertEquals(2,accepted);
        } finally { if(before==null) System.clearProperty("robotspike.hostCapture"); else System.setProperty("robotspike.hostCapture",before); }
    }
    @Test(expected=IllegalStateException.class) public void unknownPacketShapeFailsClosed() { PacingTransformer.patchHostPackets(new ClassNode()); }
}
