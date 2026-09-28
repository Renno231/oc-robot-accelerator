package ocelot.spike;

import com.google.gson.JsonObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import li.cil.oc.api.fs.FileSystem;
import li.cil.oc.api.fs.Handle;
import li.cil.oc.api.fs.Mode;
import net.minecraft.item.EnumDyeColor;
import net.minecraft.item.ItemStack;

/** Seeds native writable boot media with pinned OpenOS and the frozen Lua tree. */
final class RunnerProgram implements AutoCloseable {
    private static final long CAPACITY=32L*1024*1024;
    private final Path root;
    private final Map<String,String> hashes=new TreeMap<>();
    private String diskRoot="robot-runner-disk";
    private FileSystem observer;
    private boolean borrowedObserver;
    private long capacity=CAPACITY;
    RunnerProgram(Path root) {this.root=root;}
    // Test seam for the same live OC FileSystem API used by the runtime observer.
    RunnerProgram(Path root,FileSystem observer) {this.root=root;this.observer=observer;}
    ItemStack provision(String entry,byte[] bios) throws Exception {return provision(entry,bios,null);}
    ItemStack provision(String entry,byte[] bios,ItemStack drive) throws Exception {
        if(drive!=null) {
            li.cil.oc.api.driver.DriverItem driver=li.cil.oc.api.Driver.driverFor(drive);
            int tier=driver.tier(drive);
            capacity=li.cil.oc.Settings.get().hddSizes()[tier]*1024L;
            diskRoot=UUID.randomUUID().toString();
            net.minecraft.nbt.NBTTagCompound node=new net.minecraft.nbt.NBTTagCompound();
            node.setString("address",diskRoot); driver.dataTag(drive).setTag("node",node);
        }
        // OC FileSystem.scala:102-112 uses exactly current save root + Settings.savePath + root.
        // Never reuse imported world media: a stale runner-outcome could falsely pass.
        requireFreshDisk(net.minecraftforge.common.DimensionManager.getCurrentSaveRootDirectory().toPath(),
                li.cil.oc.Settings.savePath(),diskRoot);
        FileSystem disk=li.cil.oc.api.FileSystem.fromSaveDirectory(diskRoot,capacity,false);
        if(disk==null) throw new IOException("OC disk unavailable");
        try {
            FileSystem os=li.cil.oc.api.FileSystem.fromClass(li.cil.oc.OpenComputers.class,"opencomputers","loot/openos");
            if(os==null || !os.exists("init.lua")) throw new IOException("Pinned OpenOS assets unavailable");
            try {copyOS(os,disk,"",0);} finally {os.close();}
            // The robot component's ROM normally mounts and autoruns symlinks to these
            // exact upstream libraries. Headless rc may run before component autorun;
            // seed the same OC bytes at their OpenOS-visible /lib and /bin paths.
            FileSystem robotRom=li.cil.oc.api.FileSystem.fromClass(li.cil.oc.OpenComputers.class,
                    "opencomputers","lua/component/robot");
            if(robotRom==null || !robotRom.exists("lib/robot.lua")) throw new IOException("Pinned OC robot ROM unavailable");
            try {
                copyOS(robotRom,disk,"lib/",0);
                copyOS(robotRom,disk,"bin/",0);
                if(robotRom.isDirectory("usr/man")) copyOS(robotRom,disk,"usr/man/",0);
            } finally {robotRom.close();}
            Path program=root.resolve("program");
            if(Files.isSymbolicLink(program) || !Files.isDirectory(program)) throw new IOException("Program directory absent/link");
            int[] entries={0}; long[] bytes={0};
            copyProgram(program,program,disk,entries,bytes);
            if(!disk.exists("home/program/"+entry)) throw new IOException("Lua entry absent");
            write(disk,"etc/rc.cfg","enabled = {\"robot_runner\"}\n".getBytes(StandardCharsets.UTF_8));
            String wrapper="function start()\n"+
                "  local shell = require('shell')\n"+
                "  shell.setWorkingDirectory('/home/program')\n"+
                "  package.path = '/home/program/?.lua;/home/program/?/init.lua;' .. package.path\n"+
                "  local log = assert(io.open('/home/runner-console.log', 'w'))\n"+
                "  io.output(log)\n"+
                "  io.stderr = log\n"+
                "  _G.print = function(...) local t={} for i=1,select('#',...) do t[i]=tostring(select(i,...)) end log:write(table.concat(t,'\\t'),'\\n'); log:flush() end\n"+
                "  local ok, err = xpcall(function() assert(loadfile('/home/program/"+lua(entry)+"'))() end, debug.traceback)\n"+
                "  local outcome = assert(io.open('/home/runner-outcome', 'w'))\n"+
                "  outcome:write(ok and 'returned\\n' or 'error\\n', tostring(err or ''))\n"+
                "  outcome:close()\n"+
                "  log:flush()\n"+
                "  require('computer').shutdown()\n"+
                "end\n";
            write(disk,"etc/rc.d/robot_runner.lua",wrapper.getBytes(StandardCharsets.UTF_8));
            hashes.put("eeprom/bios.lua",hex(MessageDigest.getInstance("SHA-256").digest(bios)));
            JsonObject manifest=new JsonObject();
            for(Map.Entry<String,String> e:hashes.entrySet()) manifest.addProperty(e.getKey(),e.getValue());
            byte[] json=manifest.toString().getBytes(StandardCharsets.UTF_8);
            if(json.length>1024*1024) throw new IOException("program-inputs manifest limit");
            Files.write(root.resolve("program-inputs.json"),json,StandardOpenOption.CREATE_NEW);
        } finally {disk.close();}
        if(drive!=null) return drive; // Native HDD driver retains its capacity, speed and buffering policy.
        ItemStack floppy=li.cil.oc.api.Items.registerFloppy("robot-runner-openos",EnumDyeColor.BLUE,
            () -> li.cil.oc.api.FileSystem.fromSaveDirectory(diskRoot,CAPACITY,false),false);
        // A separate unbuffered ReadWriteFileSystem sees live on-disk files. Keep it
        // open for server-thread observation; never close the robot's own filesystem.
        observer=li.cil.oc.api.FileSystem.fromSaveDirectory(diskRoot,CAPACITY,false);
        if(observer==null) throw new IOException("OC observer disk unavailable");
        return floppy;
    }
    void observeNativeDrive(li.cil.oc.api.internal.Robot robot) {
        for(int slot=0;slot<robot.getSizeInventory();slot++) {
            Object environment=robot.getComponentInSlot(slot);
            if(environment instanceof li.cil.oc.server.component.FileSystem) {
                li.cil.oc.server.component.FileSystem fs=(li.cil.oc.server.component.FileSystem)environment;
                if(diskRoot.equals(fs.node().address())) {
                    borrow(fs.fileSystem()); return;
                }
            }
        }
        throw new IllegalStateException("configured boot drive environment absent");
    }
    void borrow(FileSystem fileSystem) {observer=fileSystem;borrowedObserver=true;}
    boolean observing() {return observer!=null;}
    static Path requireFreshDisk(Path saveRoot,String ocSavePath,String diskName) {
        Path disk=saveRoot.toAbsolutePath().normalize().resolve(ocSavePath+diskName).normalize();
        if(!disk.startsWith(saveRoot.toAbsolutePath().normalize())) throw new IllegalStateException("runner_disk_path_escape");
        if(Files.exists(disk,LinkOption.NOFOLLOW_LINKS)) throw new IllegalStateException("runner_disk_collision:"+diskName);
        return disk;
    }
    private void copyOS(FileSystem source,FileSystem target,String directory,int depth) throws Exception {
        if(depth>16) throw new IOException("OpenOS tree depth");
        String[] list=source.list(directory);
        if(list==null) throw new IOException("OpenOS directory list failed");
        for(String name:list) {
            String path=directory+name;
            if(source.isDirectory(path)) {mkdir(target,path);copyOS(source,target,path.endsWith("/")?path:path+"/",depth+1);}
            else {
                if(source.size(path)>1024*1024) throw new IOException("OpenOS file bound: "+path);
                int descriptor=source.open(path,Mode.Read);
                Handle handle=source.getHandle(descriptor);
                try {ByteArrayOutputStream output=new ByteArrayOutputStream(); byte[] b=new byte[8192]; int n;
                    while((n=handle.read(b))>0) {output.write(b,0,n);if(output.size()>1024*1024) throw new IOException("OpenOS file bound");}
                    write(target,path,output.toByteArray());
                } finally {handle.close();}
            }
        }
    }
    private void copyProgram(Path base,Path dir,FileSystem disk,int[] entries,long[] bytes) throws Exception {
        try(DirectoryStream<Path> stream=Files.newDirectoryStream(dir)) {
            for(Path child:stream) {
                if(Files.isSymbolicLink(child) || !child.toRealPath().startsWith(base.toRealPath())) throw new IOException("Program link/escape");
                String name=base.relativize(child).toString().replace('\\','/'); RunnerScenario.path(name);
                if(++entries[0]>256) throw new IOException("Program entry limit");
                String target="home/program/"+name;
                if(Files.isDirectory(child)) {mkdir(disk,target);copyProgram(base,child,disk,entries,bytes);}
                else if(Files.isRegularFile(child)) {
                    long size=Files.size(child); bytes[0]+=size;
                    if(size>1024*1024 || bytes[0]>4*1024*1024) throw new IOException("Program byte limit");
                    write(disk,target,Files.readAllBytes(child));
                } else throw new IOException("Invalid program entry");
            }
        }
    }
    private static void mkdir(FileSystem disk,String path) throws IOException {
        String[] parts=path.split("/"); String current="";
        for(String part:parts) {current+=(current.isEmpty()?"":"/")+part;if(!disk.exists(current) && !disk.makeDirectory(current)) throw new IOException("OC mkdir: "+current);}
    }
    private void write(FileSystem fs,String path,byte[] data) throws Exception {
        int slash=path.lastIndexOf('/'); if(slash>=0) mkdir(fs,path.substring(0,slash));
        int handle=fs.open(path,Mode.Write); Handle output=fs.getHandle(handle);
        try {output.write(data);} finally {output.close();}
        hashes.put("/"+path,hex(MessageDigest.getInstance("SHA-256").digest(data)));
    }
    static String hex(byte[] bytes) {StringBuilder out=new StringBuilder();for(byte b:bytes) out.append(String.format("%02x",b&255));return out.toString();}
    private static String lua(String input) {return input.replace("\\","\\\\").replace("'","\\'").replace("\n","\\n");}
    String outcome() throws Exception {
        if(observer==null) throw new IllegalStateException("OC observer disk unavailable");
        synchronized(observer) {return readOutcome();}
    }
    private String readOutcome() throws Exception {
        if(observer.size("home/runner-console.log")>1024*1024) throw new IOException("program_console_limit");
            if(!observer.exists("home/runner-outcome")) return "";
            if(observer.size("home/runner-outcome")>8192+16) throw new IOException("program_outcome_limit");
            int descriptor=observer.open("home/runner-outcome",Mode.Read);Handle handle=observer.getHandle(descriptor);
            try {ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buf=new byte[8192];int n;
                while((n=handle.read(buf))>0) {out.write(buf,0,n);if(out.size()>8208) throw new IOException("program_outcome_limit");}
                return new String(out.toByteArray(),StandardCharsets.UTF_8);
            } finally {handle.close();}
    }
    void exportConsole() throws Exception {
        if(observer==null) throw new IllegalStateException("OC observer disk unavailable");
        synchronized(observer) {copyConsole();}
    }
    private void copyConsole() throws Exception {
        if(!observer.exists("home/runner-console.log")) return;
        if(observer.size("home/runner-console.log")>1024*1024) throw new IOException("program_console_limit");
        int descriptor=observer.open("home/runner-console.log",Mode.Read);Handle handle=observer.getHandle(descriptor);
            try(OutputStream out=Files.newOutputStream(root.resolve("program.log"),StandardOpenOption.CREATE_NEW)) {
                byte[] buf=new byte[8192];int n;long bytes=0;
                while((n=handle.read(buf))>0) {bytes+=n;if(bytes>1024*1024) throw new IOException("program_console_limit");out.write(buf,0,n);}
            } finally {handle.close();}
    }
    @Override public void close() {if(observer!=null) {if(!borrowedObserver) observer.close();observer=null;}}
}
