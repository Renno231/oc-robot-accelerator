package ocelot.spike;

import java.util.Map;
import net.minecraftforge.fml.relauncher.IFMLLoadingPlugin;

@IFMLLoadingPlugin.MCVersion("1.12.2")
@IFMLLoadingPlugin.Name("RobotSpikePacing")
@IFMLLoadingPlugin.SortingIndex(1001)
@IFMLLoadingPlugin.TransformerExclusions({"ocelot.spike.PacingTransformer", "ocelot.spike.PacingPlugin"})
public final class PacingPlugin implements IFMLLoadingPlugin {
    public String[] getASMTransformerClass() { return new String[]{"ocelot.spike.PacingTransformer"}; }
    public String getModContainerClass() { return null; }
    public String getSetupClass() { return null; }
    public void injectData(Map<String, Object> data) {}
    public String getAccessTransformerClass() { return null; }
}
