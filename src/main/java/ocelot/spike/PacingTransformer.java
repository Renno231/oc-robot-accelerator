package ocelot.spike;

import net.minecraft.launchwrapper.IClassTransformer;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/** Exact-version experiment hooks. An unrecognized target shape aborts class loading. */
public final class PacingTransformer implements IClassTransformer {
    public byte[] transform(String name, String transformedName, byte[] bytes) {
        if (bytes == null) return null;
        boolean server = "net.minecraft.server.MinecraftServer".equals(transformedName);
        boolean machine = "li.cil.oc.server.machine.Machine".equals(transformedName);
        boolean safePool="li.cil.oc.util.SafeThreadPool".equals(transformedName);
        boolean chunks="net.minecraftforge.common.chunkio.ChunkIOExecutor".equals(transformedName);
        boolean chunkPool="net.minecraftforge.common.chunkio.ChunkIOThreadPoolExecutor".equals(transformedName);
        int clocks=clockSites(transformedName);
        if (!server && !machine && !safePool && !chunks && !chunkPool && clocks==0) return bytes;
        ClassNode node = new ClassNode();
        new ClassReader(bytes).accept(node, 0);
        if (server) patchPacer(node);
        if (machine) { patchObservation(node); patchSchedulerObservations(node); patchWorkerDispatch(node); }
        if(safePool) patchSafePool(node);
        if(chunks) patchChunkSubmission(node);
        if(chunkPool) patchChunkCompletion(node);
        if(clocks!=0) patchEnvironmentClocks(node,clocks);
        ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        node.accept(writer);
        return writer.toByteArray();
    }

    private static void patchPacer(ClassNode node) {
        int changes = 0;
        for (MethodNode m : node.methods) if (m.name.equals("run") && m.desc.equals("()V")) {
            String fingerprint = fingerprint(m);
            // Observed at this transformer boundary with the pinned Forge/OC binaries (see evidence).
            if (!fingerprint.equals("88861dd6729fc3761485e2f9f8a4cde72c74f8e7b8248f22bc9574f5e6dbb7b1"))
                throw new IllegalStateException("Unsupported Forge2860 server run fingerprint: " + fingerprint);
            int accumulator = -1, comparisons = 0;
            MethodInsnNode sleep = null;
            int sleeps = 0;
            for (AbstractInsnNode i : m.instructions.toArray()) {
                if (i instanceof LdcInsnNode && Long.valueOf(50).equals(((LdcInsnNode)i).cst)
                        && i.getNext() != null && i.getNext().getOpcode() == Opcodes.LCMP
                        && i.getPrevious() instanceof VarInsnNode
                        && i.getPrevious().getOpcode() == Opcodes.LLOAD) {
                    accumulator = ((VarInsnNode)i.getPrevious()).var;
                    comparisons++;
                }
                if (i instanceof MethodInsnNode) {
                    MethodInsnNode call = (MethodInsnNode)i;
                    if (call.owner.equals("java/lang/Thread") && call.name.equals("sleep") && call.desc.equals("(J)V")) {
                        sleep = call; sleeps++;
                    }
                }
            }
            if (comparisons != 1 || sleeps != 1) throw new IllegalStateException("Unrecognized 1.12.2 server pacer: " + comparisons + "/" + sleeps);
            sleep.owner = "ocelot/spike/Pacing";
            InsnList adjust = new InsnList();
            adjust.add(new VarInsnNode(Opcodes.LLOAD, accumulator));
            adjust.add(new MethodInsnNode(Opcodes.INVOKESTATIC, "ocelot/spike/Pacing", "nextAccumulator", "(J)J", false));
            adjust.add(new VarInsnNode(Opcodes.LSTORE, accumulator));
            m.instructions.insert(sleep, adjust);
            changes++;
        }
        if (changes != 1) throw new IllegalStateException("Missing server run method");
    }

    /** Hash complete instructions, operands, branches and exception handlers; omit debug metadata. */
    static String fingerprint(MethodNode method) {
        ClassWriter out = new ClassWriter(0);
        out.visit(Opcodes.V1_8, Opcodes.ACC_PUBLIC, "PacerFingerprint", null, "java/lang/Object", null);
        MethodVisitor target = out.visitMethod(method.access, method.name, method.desc, method.signature,
                method.exceptions.toArray(new String[0]));
        method.accept(new MethodVisitor(Opcodes.ASM5, target) {
            @Override public void visitLineNumber(int line, Label label) {}
            @Override public void visitLocalVariable(String name, String desc, String signature, Label start, Label end, int index) {}
            @Override public void visitFrame(int type, int locals, Object[] local, int stack, Object[] values) {}
        });
        out.visitEnd();
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256").digest(out.toByteArray());
            StringBuilder hex = new StringBuilder();
            for (byte value : hash) hex.append(String.format("%02x", value & 255));
            return hex.toString();
        } catch (NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }

    static void patchWorkerDispatch(ClassNode node) {
        int changes=0;
        for(MethodNode method:node.methods) for(AbstractInsnNode instruction:method.instructions.toArray()) {
            if(!(instruction instanceof MethodInsnNode)) continue;
            MethodInsnNode call=(MethodInsnNode)instruction;
            if(!call.owner.equals("java/util/concurrent/ScheduledExecutorService") || !call.name.equals("schedule") ||
                    !call.desc.equals("(Ljava/lang/Runnable;JLjava/util/concurrent/TimeUnit;)Ljava/util/concurrent/ScheduledFuture;")) continue;
            if(!method.name.equals("switchTo") || call.getOpcode()!=Opcodes.INVOKEINTERFACE)
                throw new IllegalStateException("Unrecognized OC worker dispatch site");
            call.setOpcode(Opcodes.INVOKESTATIC);
            call.owner="ocelot/spike/RunnerScheduler";
            call.desc="(Ljava/util/concurrent/ScheduledExecutorService;Ljava/lang/Runnable;JLjava/util/concurrent/TimeUnit;)Ljava/util/concurrent/ScheduledFuture;";
            call.itf=false;changes++;
        }
        if(changes!=1) throw new IllegalStateException("Unrecognized OC worker dispatch count: "+changes);
    }

    static void patchSafePool(ClassNode node) {
        int count=0;
        for(MethodNode method:node.methods) if(method.name.equals("withPool"))
            for(AbstractInsnNode instruction:method.instructions.toArray()) if(instruction instanceof MethodInsnNode) {
                MethodInsnNode call=(MethodInsnNode)instruction;
                if(call.owner.equals("scala/Function1") && call.name.equals("apply") && call.desc.equals("(Ljava/lang/Object;)Ljava/lang/Object;")) {
                    call.setOpcode(Opcodes.INVOKESTATIC);call.owner="ocelot/spike/RunnerAsyncWork";call.name="submit";
                    call.desc="(Lscala/Function1;Ljava/lang/Object;)Ljava/lang/Object;";call.itf=false;count++;
                }
            }
        if(count!=1) throw new IllegalStateException("Unrecognized OC async submission count: "+count);
    }
    static void patchChunkSubmission(ClassNode node) {
        int execute=0,remove=0;
        for(MethodNode method:node.methods) for(AbstractInsnNode instruction:method.instructions.toArray()) {
            if(!(instruction instanceof MethodInsnNode)) continue;
            MethodInsnNode call=(MethodInsnNode)instruction;
            if(!call.owner.equals("java/util/concurrent/ThreadPoolExecutor")) continue;
            if(call.name.equals("execute") && call.desc.equals("(Ljava/lang/Runnable;)V")) {
                call.name="executeChunk";execute++;
            } else if(call.name.equals("remove") && call.desc.equals("(Ljava/lang/Runnable;)Z")) {
                call.name="removeChunk";remove++;
            } else continue;
            call.setOpcode(Opcodes.INVOKESTATIC);call.owner="ocelot/spike/RunnerAsyncWork";
            call.desc="(Ljava/util/concurrent/ThreadPoolExecutor;"+call.desc.substring(1);call.itf=false;
        }
        if(execute!=1 || remove!=2) throw new IllegalStateException("Unrecognized Forge chunk admission: "+execute+"/"+remove);
    }
    static void patchChunkCompletion(ClassNode node) {
        int count=0;
        for(MethodNode method:node.methods) if(method.name.equals("afterExecute") && method.desc.equals("(Ljava/lang/Runnable;Ljava/lang/Throwable;)V")) {
            InsnList hook=new InsnList();hook.add(new VarInsnNode(Opcodes.ALOAD,1));
            hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC,"ocelot/spike/RunnerAsyncWork","chunkFinished","(Ljava/lang/Runnable;)V",false));
            method.instructions.insert(hook);count++;
        }
        if(count!=1) throw new IllegalStateException("Unrecognized Forge chunk completion");
    }
    /** Audited environment clocks only. CPU/watchdog/logging/retention clocks stay native. */
    private static int clockSites(String name) {
        switch(name) {
            case "li.cil.oc.server.fs.Buffered$class": return 2;
            case "li.cil.oc.server.fs.VirtualFileSystem$class": return 3;
            case "li.cil.oc.server.fs.FileOutputStreamFileSystem$class": return 1;
            case "li.cil.oc.server.fs.VirtualFileSystem$VirtualOutputHandle": return 1;
            case "li.cil.oc.server.fs.VirtualFileSystem$VirtualObject$class": return 1;
            case "li.cil.oc.server.fs.VirtualFileSystem$VirtualFile": return 1;
            case "li.cil.oc.server.fs.VirtualFileSystem$VirtualDirectory": return 3;
            case "li.cil.oc.common.EventHandler$": return 2;
            case "net.minecraft.world.World": return 2;
            case "net.minecraft.world.border.WorldBorder": return 4;
            case "net.minecraft.pathfinding.PathNavigate": return 2;
            case "net.minecraft.world.gen.structure.template.PlacementSettings": return 2;
            default: return 0;
        }
    }
    static void patchEnvironmentClocks(ClassNode node,int expected) {
        int count=0;
        for(MethodNode method:node.methods) for(AbstractInsnNode instruction:method.instructions.toArray()) {
            if(!(instruction instanceof MethodInsnNode)) continue;
            MethodInsnNode call=(MethodInsnNode)instruction;
            if(call.getOpcode()!=Opcodes.INVOKESTATIC) continue;
            if(call.desc.equals("()J") && ((call.owner.equals("java/lang/System") && call.name.equals("currentTimeMillis")) ||
                    (call.owner.equals("net/minecraft/server/MinecraftServer") && (call.name.equals("getCurrentTimeMillis") || call.name.equals("func_130071_aq"))))) {
                call.owner="ocelot/spike/RunnerScheduler";call.name="environmentMillis";count++;
            } else if(call.owner.equals("java/util/Calendar") && call.name.equals("getInstance") && call.desc.equals("()Ljava/util/Calendar;")) {
                call.owner="ocelot/spike/RunnerScheduler";call.name="environmentCalendar";count++;
            }
        }
        if(count!=expected) throw new IllegalStateException("Unrecognized environment clocks in "+node.name+": "+count+" expected "+expected);
    }

    private static void patchSchedulerObservations(ClassNode node) {
        int methods = 0;
        for (MethodNode method : node.methods) {
            if (!((method.name.equals("update") || method.name.equals("run")) && method.desc.equals("()V"))
                    && !(method.name.equals("save") && method.desc.equals("(Lnet/minecraft/nbt/NBTTagCompound;)V"))) continue;
            methods++;
            method.instructions.insert(machineObservation(method.name + ":enter"));
            for (AbstractInsnNode instruction : method.instructions.toArray()) if (instruction.getOpcode() == Opcodes.RETURN)
                method.instructions.insertBefore(instruction, machineObservation(method.name + ":return"));
        }
        if (methods != 3) throw new IllegalStateException("Unrecognized OC scheduler diagnostic methods: " + methods);
    }

    private static InsnList machineObservation(String boundary) {
        InsnList capture = new InsnList();
        capture.add(new VarInsnNode(Opcodes.ALOAD, 0));
        capture.add(new LdcInsnNode(boundary));
        capture.add(new MethodInsnNode(Opcodes.INVOKESTATIC, "ocelot/spike/Trace", "machine", "(Ljava/lang/Object;Ljava/lang/String;)V", false));
        return capture;
    }

    private static void patchObservation(ClassNode node) {
        int methods = 0, returns = 0;
        for (MethodNode m : node.methods) if (m.name.equals("invoke") && m.desc.equals("(Ljava/lang/String;Ljava/lang/String;[Ljava/lang/Object;)[Ljava/lang/Object;")) {
            methods++;
            for (AbstractInsnNode i : m.instructions.toArray()) if (i.getOpcode() == Opcodes.ARETURN) {
                InsnList capture = new InsnList();
                capture.add(new InsnNode(Opcodes.DUP));
                capture.add(new VarInsnNode(Opcodes.ALOAD, 2));
                capture.add(new VarInsnNode(Opcodes.ALOAD, 3));
                capture.add(new MethodInsnNode(Opcodes.INVOKESTATIC, "ocelot/spike/Trace", "callback", "([Ljava/lang/Object;Ljava/lang/String;[Ljava/lang/Object;)V", false));
                m.instructions.insertBefore(i, capture);
                returns++;
            }
        }
        if (methods != 1 || returns == 0) throw new IllegalStateException("Unrecognized OC 1.8.9a invocation method");
    }
}
