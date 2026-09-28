package ocelot.spike;

import org.junit.Test;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import static org.junit.Assert.*;

public class PacingTransformerTest {
    @Test(expected = IllegalStateException.class) public void rejectsCountMatchingButUnrelatedLoop() {
        // This has the old guard's two markers but no tick loop at all.
        new PacingTransformer().transform("x", "net.minecraft.server.MinecraftServer", server(true));
    }

    @Test public void unrelatedClassesRemainUntouched() {
        byte[] before = server(true);
        assertArrayEquals(before, new PacingTransformer().transform("x", "unrelated.Class", before));
    }

    @Test(expected = IllegalStateException.class) public void rejectsUnknownPacerShape() {
        new PacingTransformer().transform("x", "net.minecraft.server.MinecraftServer", server(false));
    }

    @Test public void preservesBaselineAccumulatorAndAdvancesExperimentalModes() {
        assertEquals(7, Pacing.accumulator("baseline", 7));
        assertEquals(7, Pacing.accumulator("paced", 7));
        assertEquals(51, Pacing.accumulator("unpaced", 7));
        assertEquals(51, Pacing.accumulator("coordinated", 7));
        assertEquals(90, Pacing.accumulator("unpaced", 90));
    }

    @Test public void experimentalInterruptClearsLikeThreadSleep() {
        String before = System.getProperty("robotspike.mode");
        try {
            System.setProperty("robotspike.mode", "coordinated");
            Thread.currentThread().interrupt();
            try { Pacing.sleep(50); fail("Expected interrupt"); }
            catch (InterruptedException expected) { assertFalse(Thread.currentThread().isInterrupted()); }
        } finally {
            Thread.interrupted();
            if (before == null) System.clearProperty("robotspike.mode"); else System.setProperty("robotspike.mode", before);
        }
    }

    @Test(expected = IllegalArgumentException.class) public void rejectsUnknownMode() {
        Pacing.accumulator("typo", 0);
    }

    @Test public void instrumentsSchedulerBoundariesWithoutReplacingOriginalMethods() {
        ClassWriter w = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        w.visit(Opcodes.V1_8, Opcodes.ACC_PUBLIC, "li/cil/oc/server/machine/Machine", null, "java/lang/Object", null);
        MethodVisitor invoke = w.visitMethod(Opcodes.ACC_PUBLIC, "invoke",
                "(Ljava/lang/String;Ljava/lang/String;[Ljava/lang/Object;)[Ljava/lang/Object;", null, null);
        invoke.visitCode(); invoke.visitInsn(Opcodes.ACONST_NULL); invoke.visitInsn(Opcodes.ARETURN);
        invoke.visitMaxs(0, 0); invoke.visitEnd();
        for (String name : new String[]{"update", "run", "save"}) {
            MethodVisitor m = w.visitMethod(Opcodes.ACC_PUBLIC, name,
                    name.equals("save") ? "(Lnet/minecraft/nbt/NBTTagCompound;)V" : "()V", null, null);
            m.visitCode(); m.visitInsn(Opcodes.RETURN); m.visitMaxs(0, 0); m.visitEnd();
        }
        MethodVisitor dispatch=w.visitMethod(Opcodes.ACC_PRIVATE,"switchTo","()V",null,null);
        dispatch.visitCode();dispatch.visitInsn(Opcodes.ACONST_NULL);dispatch.visitVarInsn(Opcodes.ALOAD,0);
        dispatch.visitInsn(Opcodes.LCONST_0);dispatch.visitInsn(Opcodes.ACONST_NULL);
        dispatch.visitMethodInsn(Opcodes.INVOKEINTERFACE,"java/util/concurrent/ScheduledExecutorService","schedule",
            "(Ljava/lang/Runnable;JLjava/util/concurrent/TimeUnit;)Ljava/util/concurrent/ScheduledFuture;",true);
        dispatch.visitInsn(Opcodes.POP);dispatch.visitInsn(Opcodes.RETURN);dispatch.visitMaxs(0,0);dispatch.visitEnd();
        w.visitEnd();
        byte[] transformed = new PacingTransformer().transform("x", "li.cil.oc.server.machine.Machine", w.toByteArray());
        ClassNode result = new ClassNode(); new ClassReader(transformed).accept(result, 0);
        int boundaries = 0, originalReturns = 0, schedules=0;
        for (MethodNode method : result.methods) for (AbstractInsnNode instruction : method.instructions.toArray()) {
            if (instruction instanceof MethodInsnNode) {
                MethodInsnNode call = (MethodInsnNode)instruction;
                if (call.owner.equals("ocelot/spike/Trace") && call.name.equals("machine")) boundaries++;
                if(call.owner.equals("ocelot/spike/RunnerScheduler") && call.name.equals("schedule")) {
                    schedules++;assertEquals(Opcodes.INVOKESTATIC,call.getOpcode());assertFalse(call.itf);
                    assertTrue(call.desc.startsWith("(Ljava/util/concurrent/ScheduledExecutorService;"));
                }
            }
            if (instruction.getOpcode() == Opcodes.RETURN) originalReturns++;
        }
        assertEquals(6, boundaries);
        assertEquals(4, originalReturns);assertEquals(1,schedules);
    }

    @Test(expected=IllegalStateException.class) public void missingWorkerDispatchFailsClosed() {
        PacingTransformer.patchWorkerDispatch(new ClassNode());
    }

    @Test public void pinnedAsyncAndEnvironmentClassesHaveExpectedHookShapes() throws Exception {
        String[] names={"li.cil.oc.util.SafeThreadPool","net.minecraftforge.common.chunkio.ChunkIOExecutor",
            "net.minecraftforge.common.chunkio.ChunkIOThreadPoolExecutor","li.cil.oc.server.fs.Buffered$class",
            "li.cil.oc.server.fs.VirtualFileSystem$class","li.cil.oc.server.fs.FileOutputStreamFileSystem$class",
            "li.cil.oc.server.fs.VirtualFileSystem$VirtualOutputHandle","li.cil.oc.server.fs.VirtualFileSystem$VirtualObject$class",
            "li.cil.oc.server.fs.VirtualFileSystem$VirtualFile","li.cil.oc.server.fs.VirtualFileSystem$VirtualDirectory",
            "li.cil.oc.common.EventHandler$","net.minecraft.world.World","net.minecraft.world.border.WorldBorder",
            "net.minecraft.pathfinding.PathNavigate","net.minecraft.world.gen.structure.template.PlacementSettings"};
        for(String name:names) {
            java.io.ByteArrayOutputStream out=new java.io.ByteArrayOutputStream();
            try(java.io.InputStream input=getClass().getClassLoader().getResourceAsStream(name.replace('.','/')+".class")) {
                assertNotNull(name,input);byte[] buffer=new byte[4096];int n;
                while((n=input.read(buffer))!=-1) out.write(buffer,0,n);
            }
            byte[] transformed=new PacingTransformer().transform(name,name,out.toByteArray());
            assertFalse(name,java.util.Arrays.equals(out.toByteArray(),transformed));
            // Check instruction structure; Scala's native empty inner-class debug
            // names are accepted by the JVM but rejected by ASM's metadata checker.
            new ClassReader(transformed).accept(new ClassVisitor(Opcodes.ASM5,
                    new org.objectweb.asm.util.CheckClassAdapter(new ClassWriter(0),false)) {
                @Override public void visitInnerClass(String n,String outer,String inner,int access) {}
            },0);
        }
    }
    @Test public void environmentClockHookDoesNotReplaceCpuWatchdogTime() {
        ClassNode node=new ClassNode();node.name="clock-test";
        MethodNode method=new MethodNode();node.methods.add(method);
        method.instructions.add(new MethodInsnNode(Opcodes.INVOKESTATIC,"java/lang/System","currentTimeMillis","()J",false));
        method.instructions.add(new MethodInsnNode(Opcodes.INVOKESTATIC,"java/lang/System","nanoTime","()J",false));
        PacingTransformer.patchEnvironmentClocks(node,1);
        assertEquals("environmentMillis",((MethodInsnNode)method.instructions.getFirst()).name);
        assertEquals("java/lang/System",((MethodInsnNode)method.instructions.getLast()).owner);
    }
    @Test(expected=IllegalStateException.class) public void unknownAsyncAdmissionFailsClosed() {
        PacingTransformer.patchSafePool(new ClassNode());
    }

    private static byte[] server(boolean expectedShape) {
        ClassWriter w = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        w.visit(Opcodes.V1_8, Opcodes.ACC_PUBLIC, "net/minecraft/server/MinecraftServer", null, "java/lang/Object", null);
        MethodVisitor m = w.visitMethod(Opcodes.ACC_PUBLIC, "run", "()V", null, null);
        m.visitCode();
        m.visitInsn(Opcodes.LCONST_0); m.visitVarInsn(Opcodes.LSTORE, 4);
        Label done = new Label();
        m.visitVarInsn(Opcodes.LLOAD, 4); m.visitLdcInsn(expectedShape ? 50L : 60L);
        m.visitInsn(Opcodes.LCMP); m.visitJumpInsn(Opcodes.IFLE, done);
        m.visitLabel(done);
        m.visitLdcInsn(1L);
        m.visitMethodInsn(Opcodes.INVOKESTATIC, "java/lang/Thread", "sleep", "(J)V", false);
        m.visitInsn(Opcodes.RETURN); m.visitMaxs(0, 0); m.visitEnd(); w.visitEnd();
        return w.toByteArray();
    }
}
