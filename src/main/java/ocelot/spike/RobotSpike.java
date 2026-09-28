package ocelot.spike;

import com.google.gson.JsonObject;
import com.mojang.authlib.GameProfile;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.locks.LockSupport;
import li.cil.oc.common.item.data.RobotData;
import li.cil.oc.api.internal.Robot;
import li.cil.oc.api.network.Connector;
import net.minecraft.tileentity.TileEntity;
import li.cil.oc.server.component.EEPROM;
import net.minecraft.block.Block;
import net.minecraft.init.Blocks;
import net.minecraft.init.Items;
import net.minecraft.item.ItemStack;
import net.minecraft.item.Item;
import net.minecraft.nbt.JsonToNBT;
import net.minecraft.util.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.util.EnumFacing;
import net.minecraft.util.math.BlockPos;
import net.minecraft.world.WorldServer;
import net.minecraftforge.common.ForgeChunkManager;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.common.util.FakePlayer;
import net.minecraftforge.common.util.FakePlayerFactory;
import net.minecraftforge.fml.common.Mod;
import net.minecraftforge.fml.common.event.*;
import net.minecraftforge.fml.common.eventhandler.EventPriority;
import net.minecraftforge.fml.common.eventhandler.SubscribeEvent;
import net.minecraftforge.fml.common.gameevent.TickEvent;

/** One fixed, bounded reference fixture. All Minecraft mutation stays on the server thread. */
@Mod(modid = "robotspike", name = "Robot feasibility spike", version = "0.1.0", acceptableRemoteVersions = "*", dependencies = "required-after:opencomputers@[1.8.9a,1.8.10)")
public final class RobotSpike {
    private MinecraftServer server;
    private WorldServer world;
    private Path root;
    private Robot robot;
    private EEPROM eeprom;
    private ForgeChunkManager.Ticket ticket;
    private ItemStack firmware;
    private ItemStack initialTool;
    private long started, tickStarted, ticks, maxTicks, timeoutNanos, cpuTickNanos, taskStarted;
    private JsonObject preparedGate;
    private boolean initialized, booted, finished;
    private String mode;
    private Scenario scenario;
    private RunnerScenario runnerScenario;
    private RunnerRuntime runner;
    private Field stateField;
    private final BlockPos origin = new BlockPos(0, 65, 0);

    @Mod.EventHandler public void init(FMLInitializationEvent event) throws IOException {
        root = Paths.get(System.getProperty("robotspike.root")).toRealPath();
        if (!root.equals(Paths.get("").toRealPath())) throw new IllegalStateException("Run root must be server working directory");
        RuntimeLogging.verify(root, System.getProperty("robotrunner.runtimeProfile"));
        Path runnerFile = root.resolve("runner-scenario.json");
        if (Files.exists(runnerFile)) {
            if (Files.isSymbolicLink(runnerFile) || Files.size(runnerFile) > 128 * 1024) throw new IllegalArgumentException("Runner scenario file bound");
            runnerScenario = RunnerScenario.parse(new String(Files.readAllBytes(runnerFile), StandardCharsets.UTF_8));
            MinecraftForge.EVENT_BUS.register(this);
            ForgeChunkManager.setForcedChunkLoadingCallback(this, (ForgeChunkManager.LoadingCallback)(tickets, world) -> {
                for (ForgeChunkManager.Ticket old : tickets) ForgeChunkManager.releaseTicket(old);
            });
            return;
        }
        Path scenarioFile = root.resolve("scenario.json");
        if (Files.exists(scenarioFile) && (Files.isSymbolicLink(scenarioFile) || Files.size(scenarioFile) > 1024))
            throw new IllegalArgumentException("Scenario file bound");
        scenario = Scenario.parse(Files.exists(scenarioFile)
                ? new String(Files.readAllBytes(scenarioFile), StandardCharsets.UTF_8) : "{}");
        byte[] code;
        try (InputStream in = getClass().getResourceAsStream("/robot.lua"); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            if (in == null) throw new IOException("Missing robot firmware");
            byte[] buffer = new byte[4096]; int count;
            while ((count = in.read(buffer)) >= 0) out.write(buffer, 0, count);
            code = out.toByteArray();
        }
        code = new String(code, StandardCharsets.UTF_8)
                .replace("for i = 1, 8 do", "for i = 1, " + scenario.laps + " do")
                .replace("__PREPARED_START__", Boolean.toString(scenario.preparedStart)).getBytes(StandardCharsets.UTF_8);
        if (code.length > 4096) throw new IOException("Firmware exceeds EEPROM capacity");
        firmware = li.cil.oc.api.Items.registerEEPROM("robot-spike", code, new byte[0], false);
        MinecraftForge.EVENT_BUS.register(this);
        ForgeChunkManager.setForcedChunkLoadingCallback(this, (ForgeChunkManager.LoadingCallback)(tickets, world) -> {
            for (ForgeChunkManager.Ticket old : tickets) ForgeChunkManager.releaseTicket(old);
        });
    }

    @Mod.EventHandler public void started(FMLServerStartedEvent event) throws Exception {
        server = net.minecraftforge.fml.common.FMLCommonHandler.instance().getMinecraftServerInstance();
        world = server.getWorld(0);
        mode = Pacing.mode();
        if (runnerScenario != null) {
            if (!runnerScenario.mode.equals(mode) || li.cil.oc.Settings.get().executionDelay() != runnerScenario.delay)
                throw new IllegalStateException("runner execution profile mismatch");
            maxTicks = runnerScenario.maxTicks;
            timeoutNanos = runnerScenario.timeoutSeconds * 1000000000L;
            runner = new RunnerRuntime(runnerScenario, world, root);
        } else {
            maxTicks = bounded("robotspike.maxTicks", 10000, 1, 10000);
            timeoutNanos = bounded("robotspike.timeoutSeconds", 120, 1, 600) * 1000000000L;
        }
        started = System.nanoTime();
        Trace.open(root, runnerScenario == null && scenario.trace);
        if (li.cil.oc.Settings.get().httpEnabled() || li.cil.oc.Settings.get().tcpEnabled() || li.cil.oc.Settings.get().ignorePower())
            throw new IllegalStateException("OC must disable Internet and retain power accounting");
        initialized = true;
    }

    @SubscribeEvent(priority = EventPriority.HIGHEST) public void startTick(TickEvent.ServerTickEvent event) {
        if (event.phase != TickEvent.Phase.START || !initialized || finished) return;
        tickStarted = System.nanoTime();
        Trace.tick = ++ticks;
    }

    @SubscribeEvent(priority = EventPriority.LOWEST) public void endTick(TickEvent.ServerTickEvent event) {
        if (event.phase != TickEvent.Phase.END || !initialized || finished) return;
        try {
            if (System.nanoTime() - started > timeoutNanos) { finish(false, "wall_limit"); return; }
            int chunks = 0;
            for (WorldServer dimension : server.worlds) chunks += dimension.getChunkProvider().getLoadedChunkCount();
            if (chunks > 2048) { finish(false, "chunk_limit:" + chunks); return; }
            if (runner != null) {
                if (!runner.ready()) setup();
                else {
                    String outcome = runner.tick(ticks, mode);
                    if (outcome != null) { finish(outcome.equals("passed"), outcome); return; }
                }
                cpuTickNanos += System.nanoTime() - tickStarted;
                if (ticks >= maxTicks) finish(false, "tick_limit");
                return;
            }
            if (robot == null) setup();
            else if (!booted) {
                if (robot.node().network() != null && ticks >= 3) {
                    for (int slot = 0; slot < robot.getSizeInventory(); slot++) {
                        if (robot.getComponentInSlot(slot) instanceof EEPROM) eeprom = (EEPROM)robot.getComponentInSlot(slot);
                    }
                    if (eeprom == null) throw new IllegalStateException("EEPROM environment absent");
                    if (!robot.machine().start()) throw new IllegalStateException("Robot would not start: " + robot.machine().lastError());
                    booted = true;
                }
            } else {
                if (mode.equals("coordinated")) awaitWorker();
                String data = new String(eeprom.volatileData(), StandardCharsets.UTF_8);
                if (scenario.preparedStart && taskStarted == 0 && ticks >= 100) releasePreparedTask(data);
                if (firmwareFinished(data, machineState())) {
                    boolean correct = data.equals("PASS:" + (1 + 4 * scenario.laps)) && ((TileEntity)robot).getPos().equals(origin)
                            && world.isAirBlock(origin.north()) && world.isAirBlock(origin.north(2))
                            && robot.mainInventory().getStackInSlot(0).getCount() == 17
                            && robot.getStackInSlot(0).getItem() == initialTool.getItem()
                            && (initialTool.getItem() != Items.DIAMOND_PICKAXE
                                || robot.getStackInSlot(0).getItemDamage() <= initialTool.getItemDamage() + 1 + scenario.laps);
                    finish(correct, data); return;
                }
                if (!robot.machine().isRunning() && robot.machine().lastError() != null) {
                    finish(false, "robot_error:" + robot.machine().lastError()); return;
                }
            }
            if (scenario.trace) {
                JsonObject observation = snapshot();
                observation.addProperty("kind", "tick"); observation.addProperty("loadedChunks", chunks);
                observation.addProperty("tickWorkNanos", System.nanoTime() - tickStarted);
                Trace.record(observation);
            }
            cpuTickNanos += System.nanoTime() - tickStarted;
            if (ticks >= maxTicks) finish(false, "tick_limit");
        } catch (Exception e) {
            e.printStackTrace();
            finish(false, e.getClass().getSimpleName() + ":" + e.getMessage());
        }
    }

    private void setup() throws Exception {
        if (runner != null) {
            ticket = ForgeChunkManager.requestTicket(this, world, ForgeChunkManager.Type.NORMAL);
            if (ticket == null) throw new IllegalStateException("Chunk ticket unavailable");
            for (int x = Math.floorDiv(runnerScenario.min[0], 16); x <= Math.floorDiv(runnerScenario.max[0], 16); x++)
                for (int z = Math.floorDiv(runnerScenario.min[2], 16); z <= Math.floorDiv(runnerScenario.max[2], 16); z++)
                    ForgeChunkManager.forceChunk(ticket, new net.minecraft.util.math.ChunkPos(x, z));
            runner.setup(); return;
        }
        ticket = ForgeChunkManager.requestTicket(this, world, ForgeChunkManager.Type.NORMAL);
        if (ticket == null) throw new IllegalStateException("Chunk ticket unavailable");
        for (int x = -1; x <= 1; x++) for (int z = -1; z <= 1; z++)
            ForgeChunkManager.forceChunk(ticket, new net.minecraft.util.math.ChunkPos(x, z));
        for (int x = -3; x <= 3; x++) for (int z = -4; z <= 3; z++) {
            world.setBlockState(new BlockPos(x, 64, z), Blocks.STONE.getDefaultState(), 3);
            for (int y = 65; y <= 67; y++) world.setBlockToAir(new BlockPos(x, y, z));
        }
        world.setBlockState(origin.north(), Blocks.STONE.getDefaultState(), 3);
        RobotData data = new RobotData();
        data.name_$eq("spike-robot"); data.tier_$eq(2);
        data.robotEnergy_$eq(50000); data.totalEnergy_$eq(50000);
        data.components_$eq(new ItemStack[]{item("cpu3"), item("ram6"), item("inventoryupgrade"), firmware.copy()});
        ItemStack stack = data.createItemStack();
        Block block = Block.getBlockFromItem(stack.getItem());
        world.setBlockState(origin, block.getDefaultState(), 3);
        FakePlayer owner = FakePlayerFactory.get(world, new GameProfile(UUID.fromString("933cfa95-d269-48dd-8ed0-3c38ef1983fa"), "spike-owner"));
        owner.setPosition(0.5, 65, 1.5); owner.rotationYaw = 180;
        block.onBlockPlacedBy(world, origin, world.getBlockState(origin), owner, stack);
        Object proxy = world.getTileEntity(origin);
        robot = (Robot)proxy.getClass().getMethod("robot").invoke(proxy);
        robot.getClass().getMethod("setFromFacing", EnumFacing.class).invoke(robot, EnumFacing.NORTH);
        robot.getClass().getMethod("connectComponents").invoke(robot);
        Path toolFile = root.resolve("tool.json");
        String toolJson = "{}";
        if (Files.exists(toolFile)) {
            if (Files.isSymbolicLink(toolFile) || Files.size(toolFile) > 8192) throw new IllegalArgumentException("Tool file bound");
            toolJson = new String(Files.readAllBytes(toolFile), StandardCharsets.UTF_8);
        }
        ToolSelection tool = ToolSelection.parse(toolJson);
        ResourceLocation itemId = new ResourceLocation(tool.item);
        if (!Item.REGISTRY.containsKey(itemId) || Item.REGISTRY.getObject(itemId) == Items.AIR)
            throw new IllegalArgumentException("Tool mod/item is not installed: " + tool.item);
        initialTool = new ItemStack(Item.REGISTRY.getObject(itemId), 1, tool.metadata);
        initialTool.setTagCompound(JsonToNBT.getTagFromJson(tool.nbt));
        robot.setInventorySlotContents(0, initialTool.copy());
        robot.mainInventory().setInventorySlotContents(0, new ItemStack(Blocks.COBBLESTONE, 16));
        stateField = robot.machine().getClass().getDeclaredField("state");
        stateField.setAccessible(true);
    }

    static boolean firmwareFinished(String data, String state) {
        return !data.isEmpty() && state.equals("Stopped");
    }

    static boolean workerNeedsTime(String state, boolean executing) {
        return executing || state.equals("Yielded") || state.equals("SynchronizedReturn") || state.equals("Running");
    }

    /** A bounded experimental rendezvous, not a proof of equivalence for arbitrary yields. */
    private void awaitWorker() throws Exception {
        long deadline = System.nanoTime() + 1000000000L;
        while (true) {
            String state = machineState();
            if (!workerNeedsTime(state, ((li.cil.oc.server.machine.Machine)robot.machine()).isExecuting())) return;
            if (System.nanoTime() >= deadline || System.nanoTime() - started > timeoutNanos || Thread.currentThread().isInterrupted())
                throw new IllegalStateException("worker_progress_limit:" + state);
            LockSupport.parkNanos(10000L);
        }
    }

    /** Fixture preparation ends at LOWEST server END tick 100; no resource reset follows release. */
    private void releasePreparedTask(String data) throws Exception {
        if (ticks != 100 || !data.equals("READY") || !machineState().equals("Sleeping")
                || ((li.cil.oc.server.machine.Machine)robot.machine()).isExecuting()
                || Trace.actionCount() != 0 || !((TileEntity)robot).getPos().equals(origin)
                || robot.facing() != EnumFacing.NORTH || robot.mainInventory().getStackInSlot(0).getCount() != 16
                || world.getBlockState(origin.north()).getBlock() != Blocks.STONE || !world.isAirBlock(origin.north(2)))
            throw new IllegalStateException("prepared_start_not_ready");
        Object signals = field("signals");
        int queued;
        synchronized (signals) { queued = ((scala.collection.mutable.Queue<?>)signals).size(); }
        if (queued != 0) throw new IllegalStateException("prepared_start_pending_signals");
        Connector connector = (Connector)robot.machine().node();
        double previousEnergy = connector.globalBuffer();
        connector.changeBuffer(20000.0 - previousEnergy);
        if (connector.globalBuffer() != 20000.0) throw new IllegalStateException("prepared_start_energy_capacity");
        preparedGate = snapshot();
        preparedGate.addProperty("kind", "prepared_gate");
        preparedGate.addProperty("queuedSignals", queued);
        preparedGate.addProperty("callbacksBeforeGate", Trace.actionCount());
        preparedGate.addProperty("energyBeforePreparation", previousEnergy);
        preparedGate.addProperty("hostCpuSeconds", robot.machine().cpuTime());
        taskStarted = System.nanoTime();
        Trace.record(preparedGate);
        if (!robot.machine().signal("spike_go")) throw new IllegalStateException("prepared_start_signal_rejected");
    }

    private Object field(String name) throws Exception {
        Field field = robot.machine().getClass().getDeclaredField(name);
        field.setAccessible(true);
        return field.get(robot.machine());
    }

    private String machineState() throws Exception {
        Object stack = stateField.get(robot.machine());
        synchronized (stack) { return String.valueOf(stack.getClass().getMethod("top").invoke(stack)); }
    }

    private JsonObject snapshot() throws Exception {
        JsonObject value = new JsonObject();
        if (robot != null) {
            BlockPos pos = ((TileEntity)robot).getPos();
            value.addProperty("x", pos.getX()); value.addProperty("y", pos.getY()); value.addProperty("z", pos.getZ());
            value.addProperty("facing", robot.facing().toString());
            value.addProperty("energy", ((Connector)robot.machine().node()).globalBuffer());
            value.addProperty("uptime", robot.machine().upTime());
            value.addProperty("state", machineState());
            value.addProperty("workerExecuting", ((li.cil.oc.server.machine.Machine)robot.machine()).isExecuting());
            value.addProperty("worldTotalTime", world.getTotalWorldTime());
            value.addProperty("serverTick", server.getTickCounter());
            value.addProperty("savePhase", server.getTickCounter() % 900);
            value.addProperty("debitPhase", world.getTotalWorldTime() % li.cil.oc.Settings.get().tickFrequency());
            value.addProperty("frontBlock", String.valueOf(world.getBlockState(origin.north()).getBlock().getRegistryName()));
            value.addProperty("farBlock", String.valueOf(world.getBlockState(origin.north(2)).getBlock().getRegistryName()));
            value.addProperty("inventoryCount", robot.mainInventory().getStackInSlot(0).getCount());
            value.addProperty("toolDamage", robot.getStackInSlot(0).getItemDamage());
            value.addProperty("toolItem", String.valueOf(robot.getStackInSlot(0).getItem().getRegistryName()));
        }
        return value;
    }

    private void finish(boolean passed, String reason) {
        if (finished) return;
        finished = true;
        try {
            JsonObject result;
            if (runner != null) {
                result = runner.result(ticks);
                reason = runnerFinalReason(passed, reason, result);
                if (result.has("runnerArtifactError")) passed = false;
            } else {
                try { result = snapshot(); }
                catch (Exception e) { result = new JsonObject(); result.addProperty("observationError", e.toString()); passed = false; }
            }
            result.addProperty("status", passed ? "passed" : "failed"); result.addProperty("reason", reason);
            result.addProperty("mode", mode); result.addProperty("ticks", ticks);
            result.addProperty("elapsedNanos", System.nanoTime() - started);
            result.addProperty("tickWorkNanos", cpuTickNanos);
            result.addProperty("actionSpanNanos", Trace.actionSpanNanos());
            if (runner == null) {
                result.addProperty("laps", scenario.laps);
                result.addProperty("preparedStart", scenario.preparedStart);
                result.addProperty("taskElapsedNanos", taskStarted == 0 ? 0 : System.nanoTime() - taskStarted);
                if (preparedGate != null) result.add("preparedGate", preparedGate);
            }
            result.addProperty("traceEnabled", runner == null && scenario.trace);
            result.addProperty("executionDelayMillis", li.cil.oc.Settings.get().executionDelay());
            result.addProperty("maxLoadedChunks", 2048);
            result.addProperty("workerProgressLimitMillis", 1000);
            if (runner == null && initialTool != null) {
                result.addProperty("initialTool", initialTool.serializeNBT().toString());
                result.addProperty("finalTool", robot.getStackInSlot(0).serializeNBT().toString());
                result.addProperty("toolWearOracle", initialTool.getItem() == Items.DIAMOND_PICKAXE ? "vanilla-range" : "observed-only");
            }
            if (eeprom != null) result.addProperty("firmwareResult", new String(eeprom.volatileData(), StandardCharsets.UTF_8));
            Trace.close();
            Path temporary = root.resolve("result.json.tmp");
            byte[] payload = result.toString().getBytes(StandardCharsets.UTF_8);
            if (payload.length > 1024 * 1024) throw new IOException("result_limit");
            Files.write(temporary, payload, StandardOpenOption.CREATE_NEW);
            Files.move(temporary, root.resolve("result.json"), StandardCopyOption.ATOMIC_MOVE);
        } catch (Exception e) { e.printStackTrace(); }
        finally {
            if (ticket != null) { ForgeChunkManager.releaseTicket(ticket); ticket = null; }
            server.initiateShutdown();
        }
    }

    static String runnerFinalReason(boolean passed, String reason, JsonObject result) {
        if (!result.has("runnerArtifactError")) return reason;
        String error = result.get("runnerArtifactError").getAsString();
        String detail = "runner_artifact_error:" + error;
        if (!passed) detail = reason + ";" + detail;
        return detail.substring(0, Math.min(8192, detail.length()));
    }
    @Mod.EventHandler public void stopped(FMLServerStoppedEvent event) throws IOException { Trace.close(); }
    private static ItemStack item(String name) {
        if (li.cil.oc.api.Items.get(name) == null) throw new IllegalArgumentException("Missing OC item " + name);
        return li.cil.oc.api.Items.get(name).createItemStack(1);
    }
    private static long bounded(String name, long fallback, long minimum, long maximum) {
        long value = Long.parseLong(System.getProperty(name, Long.toString(fallback)));
        if (value < minimum || value > maximum) throw new IllegalArgumentException(name + " outside bounds");
        return value;
    }
}
