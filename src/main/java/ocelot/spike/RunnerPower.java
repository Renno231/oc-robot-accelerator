package ocelot.spike;

import com.google.gson.*;
import java.util.*;
import li.cil.oc.api.network.Connector;
import net.minecraft.tileentity.TileEntity;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.WorldServer;

/** One-time native block placement/connector initialization; never tops up power. */
final class RunnerPower {
    private final WorldServer world;
    private final JsonArray blocks;
    private final Set<BlockPos> initialized=new HashSet<>();
    RunnerPower(RunnerScenario spec,WorldServer world) {this.world=world;blocks=spec.v4.placedBlocks;}
    void setup() {
        for(JsonElement e:blocks) {
            JsonObject b=e.getAsJsonObject();world.setBlockState(RunnerContainers.pos(b),RunnerRuntime.blockState(b),3);
        }
    }
    boolean initialize(long tick) throws Exception {
        if(tick<3) return false;
        for(JsonElement e:blocks) {
            JsonObject b=e.getAsJsonObject();if(!b.has("energy")) continue;
            BlockPos p=RunnerContainers.pos(b);if(initialized.contains(p)) continue;
            TileEntity tile=world.getTileEntity(p);
            if(tile==null || RunnerRuntime.isMachineTile(tile.getClass())) throw new IllegalArgumentException("block energy requires native non-machine OC connector: "+p);
            Object node;
            try {node=tile.getClass().getMethod("node").invoke(tile);}
            catch(ReflectiveOperationException ex) {throw new IllegalArgumentException("block energy requires native OC connector: "+p,ex);}
            if(!(node instanceof Connector)) throw new IllegalArgumentException("block energy requires native OC connector: "+p);
            Connector connector=(Connector)node;if(connector.network()==null) return false;
            double energy=b.get("energy").getAsDouble();
            if(energy>connector.localBufferSize()) throw new IllegalArgumentException("block energy exceeds native local capacity at "+p+": "+connector.localBufferSize());
            connector.changeBuffer(energy-connector.localBuffer());initialized.add(p);
        }
        return true;
    }
}
