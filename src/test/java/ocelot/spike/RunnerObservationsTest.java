package ocelot.spike;

import com.google.gson.JsonObject;
import java.util.HashMap;
import java.util.Map;
import net.minecraft.block.BlockChest;
import net.minecraft.block.state.IBlockState;
import net.minecraft.init.Blocks;
import net.minecraft.init.Bootstrap;
import net.minecraft.util.EnumFacing;
import net.minecraft.util.math.BlockPos;
import org.junit.Test;
import static org.junit.Assert.*;

public class RunnerObservationsTest {
    @Test public void recordsInitialChangesAndReversalsButSkipsUnchangedNativeStates() {
        Bootstrap.register();
        Map<BlockPos,IBlockState> previous=new HashMap<>();
        BlockPos first=new BlockPos(0,65,0),second=new BlockPos(1,65,0);
        IBlockState north=Blocks.CHEST.getDefaultState().withProperty(BlockChest.FACING,EnumFacing.NORTH);
        IBlockState south=north.withProperty(BlockChest.FACING,EnumFacing.SOUTH);
        JsonObject initial=RunnerObservations.changedBlock(previous,first,north);
        assertEquals("minecraft:chest",initial.get("block").getAsString());
        assertEquals("north",initial.getAsJsonObject("properties").get("facing").getAsString());
        assertNull(RunnerObservations.changedBlock(previous,new BlockPos(0,65,0),north));
        assertEquals("south",RunnerObservations.changedBlock(previous,first,south)
                .getAsJsonObject("properties").get("facing").getAsString());
        assertEquals(initial,RunnerObservations.changedBlock(previous,first,north));
        assertNotNull(RunnerObservations.changedBlock(previous,second,north));
        assertEquals("minecraft:air",RunnerObservations.changedBlock(previous,first,Blocks.AIR.getDefaultState())
                .get("block").getAsString());
        assertNull(RunnerObservations.changedBlock(previous,first,Blocks.AIR.getDefaultState()));
        assertEquals(2,previous.size());
        // Emitted snapshots do not change when the cached state is replaced.
        assertEquals("north",initial.getAsJsonObject("properties").get("facing").getAsString());
    }
}
