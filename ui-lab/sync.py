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
for _,a in ipairs(args) do if a=="announce" then
  local function fire() require("logistics").labAnnounce();require("mes").labAnnounce() end
  announce=event.timer(6,fire)
end end
if args[2]=="mem" then
  local low=math.huge
  opts.status=function()
    local f=computer.freeMemory();low=math.min(low,f)
    return string.format("free %dk (low %dk) of %dk",f//1024,low//1024,computer.totalMemory()//1024)
  end
  timer=event.timer(1,function() computer.pushSignal("mes","tick") end,math.huge)
end
require("mes_ui").run(opts)
if timer then event.cancel(timer) end
if announce then event.cancel(announce) end
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
