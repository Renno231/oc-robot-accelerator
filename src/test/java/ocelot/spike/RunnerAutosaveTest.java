package ocelot.spike;

import org.junit.Test;
import static org.junit.Assert.*;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.*;

public class RunnerAutosaveTest {
    @Test public void nativeDefaultAndWallClockGate() {
        RunnerAutosave.configureAt(0,0);
        assertEquals(1,RunnerAutosave.remainderAt(901,90000000000L));
        assertEquals(0,RunnerAutosave.remainderAt(1800,90000000000L));
        RunnerAutosave.configureAt(45,100);
        assertEquals(1,RunnerAutosave.remainderAt(900,44999999999L));
        assertEquals(0,RunnerAutosave.remainderAt(901,45000000100L));
        assertEquals(1,RunnerAutosave.remainderAt(1800,45000000101L));
        assertEquals(0,RunnerAutosave.remainderAt(1801,90000000100L));
        assertEquals(2,RunnerAutosave.report().get("periodicSaveBranches").getAsInt());
        RunnerAutosave.configure(0);
    }
    @Test public void maximumIntervalDoesNotOverflow() {
        RunnerAutosave.configureAt(Integer.MAX_VALUE,0);
        assertEquals(1,RunnerAutosave.remainderAt(900,100000000000L));
        assertEquals(0,RunnerAutosave.remainderAt(901,Integer.MAX_VALUE*1000000000L));
        RunnerAutosave.configure(0);
    }
    @Test public void patchOnlyReplacesPeriodicGate() {
        ClassNode node=new ClassNode();
        MethodNode tick=new MethodNode(Opcodes.ACC_PUBLIC,"tick","()V",null,null);
        tick.instructions.add(new InsnNode(Opcodes.ICONST_1));
        tick.instructions.add(new IntInsnNode(Opcodes.SIPUSH,900));
        tick.instructions.add(new InsnNode(Opcodes.IREM));
        tick.instructions.add(new InsnNode(Opcodes.POP));
        tick.instructions.add(new InsnNode(Opcodes.RETURN));node.methods.add(tick);
        PacingTransformer.patchAutosave(node);
        assertTrue(tick.instructions.get(1) instanceof MethodInsnNode);
        assertEquals("remainder",((MethodInsnNode)tick.instructions.get(1)).name);
        assertEquals(4,tick.instructions.size());
    }
    @Test(expected=IllegalStateException.class) public void rejectsUnknownServerShape() {
        PacingTransformer.patchAutosave(new ClassNode());
    }
}
