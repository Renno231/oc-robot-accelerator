"""Copy the UI, qmenu and the contract fakes onto the lab disk.

The lab is a T3 computer/screen in ocelotharness running the production UI
against fakes of the T11 API contract (fakes/):

    python ui-lab/sync.py
    ocelot-harnessd up --project ui-lab
    ocelotctl --project ui-lab machine start main
    ocelotctl --project ui-lab screen type main-screen "mesui craft"   (then key-down enter)
"""
import os
import shutil
import zipfile
from pathlib import Path

# `mesui TAB` opens a tab; `mesui TAB mem` also shows free memory in the
# header, refreshed every second (raw: garbage not yet collected counts).
# `mesui TAB mem announce` (or `TAB x announce`) has a drone and a robot
# announce 6 s after start.
LAUNCHER = """local args={...}
local computer=require("computer");local event=require("event")
local opts={tab=args[1]};local timer,announce
-- `announce` anywhere after the tab: 6 s in, a drone and a robot announce.
-- `releasetimeout` / `releaseempty` anywhere after the tab: drone releases
-- time out (5 s) / report an empty drone.
for _,a in ipairs(args) do if a=="releasetimeout" then require("logistics").labReleaseTimeout=true end
  if a=="releaseempty" then require("logistics").labReleaseEmpty=true end end
for _,a in ipairs(args) do if a=="announce" then
  local function fire() require("logistics").labAnnounce();require("mes").labAnnounce() end
  announce=event.timer(6,fire)
end end
-- `sensor`: 6 s in, a sensor announces. `deposit`: 6 s in, items land in
-- IO chest in1 (its sensor reports them). `sensorlist`: logistics gets the
-- proposed sensors() (not in the real API).
local labTimers={}
for _,a in ipairs(args) do
  if a=="sensor" then local function fire() require("logistics").labAnnounceSensor() end;labTimers[#labTimers+1]=event.timer(6,fire) end
  if a=="deposit" then local function fire() require("iochest").labDeposit() end;labTimers[#labTimers+1]=event.timer(6,fire) end
  if a=="sensorlist" then require("logistics").labSensorList() end
  -- `whchange`: 10 s in, 640 cobblestone arrive (a warehouse "changed").
  if a=="whchange" then local function fire() require("warehouse").labChange() end;labTimers[#labTimers+1]=event.timer(10,fire) end
  -- `stats76` (default), `stats96`, `statsempty`, `statsunread`: the stats scenario.
  if a:match("^stats%w+$") then require("stats").labScenario(a:sub(6)) end
  -- `timing`: machines in every learned-timing case (fakes/mes.lua).
  if a=="timing" then require("mes").labTiming() end
  -- `learn` (with `timing`): 10 s in, pressA learns a lower bound and
  -- signals ('mes','timing','pressA') as mes_timing.persist does.
  if a=="learn" then local function fire() require("mes").labLearn() end;labTimers[#labTimers+1]=event.timer(10,fire) end
  -- `alerts3`: three active alerts of different kinds at start (fakes/mes_alerts.lua).
  if a=="alerts3" then require("mes_alerts").labThree() end
  -- `alertshist`: failed runs (item, old id-only), a stuck machine named
  -- with a colon, a dismissed-then-cleared alert, one expiring 20 s in.
  if a=="alertshist" then require("mes_alerts").labHistory() end
  -- `alertcycle`: one-shot timers, 10 s apart from 15 s: drone3 held too
  -- long is raised; drone5 lost clears; furnaceA load 3 stuck is dismissed
  -- (as from another screen); a run making stone bricks fails.
  if a=="alertcycle" then
    local al=require("mes_alerts")
    local function held() al.labRaise("droneHeld","drone3","Cargo held: drone3") end
    local function found() al.labClear("droneLost","drone5") end
    local function elsewhere() al.labDismiss("machineStuck","furnaceA:3") end
    local function failed() al.labRaise("runFailed","7b3e90c1d24f6a85e0c9b7d13a2f4e68","Run failed: minecraft:stonebrick",nil,nil,nil,"minecraft:stonebrick") end
    for k,f in ipairs({held,found,elsewhere,failed}) do labTimers[#labTimers+1]=event.timer(5+k*10,f) end
  end
end
if args[2]=="mem" then
  -- settled: the most free over the last 10 samples, i.e. after the
  -- kernel's periodic full collection (live memory, garbage excluded).
  local low,last=math.huge,{}
  opts.status=function()
    local f=computer.freeMemory();low=math.min(low,f)
    table.insert(last,f);if #last>10 then table.remove(last,1) end
    -- settled, then low: an alert bar may leave room for only part of this.
    return string.format("settled %dk · low %dk · free %dk · of %dk",math.max(table.unpack(last))//1024,low//1024,f//1024,computer.totalMemory()//1024)
  end
  timer=event.timer(1,function() computer.pushSignal("mes","tick") end,math.huge)
end
require("mes_ui").run(opts)
if timer then event.cancel(timer) end
if announce then event.cancel(announce) end
for _,t in ipairs(labTimers) do event.cancel(t) end
"""

lab = Path(__file__).resolve().parent
root = lab.parent
disk = lab / "disk"
lib = disk / "usr" / "lib"
# OpenOS comes from the OpenComputers jar (OC_JAR overrides the default).
OC_JAR = os.environ.get("OC_JAR", "C:/or/drone-install-T8/acquired/OpenComputers-1.8.9a.jar")
if not (disk / "init.lua").exists():
    prefix = "assets/opencomputers/loot/openos/"
    with zipfile.ZipFile(OC_JAR) as jar:
        for name in jar.namelist():
            if name.startswith(prefix) and not name.endswith("/"):
                out = disk / name[len(prefix):]
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(jar.read(name))
shutil.rmtree(lib / "mes_ui", ignore_errors=True)
shutil.copytree(root / "craftsystem" / "usr" / "lib" / "mes_ui", lib / "mes_ui")
shutil.copy(root / "fixtures" / "qmenu.lua", disk / "lib" / "qmenu.lua")
# The crafting system's own libraries run headless (management screens,
# plans, kits, tools, stockkeeper): the real ones, except the MES library
# itself, which the fakes below replace with the T11 contract fake.
for f in (root / "craftsystem" / "usr" / "lib").glob("*.lua"):
    if f.name != "mes.lua":
        shutil.copy(f, lib / f.name)
for f in (lab / "fakes").glob("*.lua"):
    shutil.copy(f, lib / f.name)
(disk / "usr" / "bin").mkdir(parents=True, exist_ok=True)
(disk / "usr" / "bin" / "mesui.lua").write_text(LAUNCHER, newline="\n")
print("synced to", disk)
