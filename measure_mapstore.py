"""Controller Lua-heap comparison using the unchanged 20-drone SCALE map geometry.

Real OpenOS serialization, canonical CBOR/store/map/stations; host-backed files
keep simulated HDD bytes outside the Lua heap. Warehouse/logistics only complete
commissioning reads here: this is a map-size-equivalent, not native total RAM.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from lupa.lua53 import LuaRuntime
from supervisor import NO_WINDOW


def measure(builder, serializer, before):
    lua = LuaRuntime(encoding=None, unpack_returned_tuples=True)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        handles = []

        def path(name):
            return root / name.decode().lstrip('/')

        def open_file(name, mode):
            p = path(name)
            mode = mode.decode().replace('b', '') + 'b'
            if mode.startswith('r') and not p.exists():
                return None
            p.parent.mkdir(parents=True, exist_ok=True)
            handle = p.open(mode)
            handles.append(handle)
            return handle

        def read_file(handle, count):
            value = handle.read(-1 if count == b'*a' else count)
            return value if value or count in (b'*a', 0) else None

        def rename(a, b):
            path(a).replace(path(b))
            return True

        g = lua.globals()
        g.PY_OPEN = open_file
        g.PY_READ = read_file
        g.PY_WRITE = lambda h, s: h.write(s)
        g.PY_FLUSH = lambda h: (h.flush(), True)[1]
        g.PY_CLOSE = lambda h: h.close()
        g.PY_EXISTS = lambda p: path(p).exists()
        g.PY_RENAME = rename
        g.PY_REMOVE = lambda p: (path(p).unlink(), True)[1]
        g.SERIALIZER = serializer
        for name in ('map', 'stations', 'store', 'cbor'):
            source = (subprocess.check_output(['git', 'show', f'496478c:drone-logistics/lib/{name}.lua'],
                                              creationflags=NO_WINDOW)
                      if before and name in ('map', 'stations') else Path(f'drone-logistics/lib/{name}.lua').read_bytes())
            g[(name.upper() + '_SOURCE').encode()] = source
        lua.execute('''
          function checkArg(n,v,t) assert(type(v)==t,'argument '..n..' requires '..t) end
          package.preload.serialization=function() return assert(load(SERIALIZER))() end
          package.preload.filesystem=function() return {exists=PY_EXISTS,rename=PY_RENAME,remove=PY_REMOVE} end
          os.rename=PY_RENAME
          io.open=function(p,m)
            local file=PY_OPEN(p,m or 'r');if not file then return nil end
            local h={}
            function h:write(s) PY_WRITE(file,s);return h end
            function h:read(n) return PY_READ(file,n) end
            function h:flush() return PY_FLUSH(file) end
            function h:close() PY_CLOSE(file) end
            return h
          end
          for _,n in ipairs({'map','stations','store','cbor'}) do
            package.preload[n]=function() return assert(load(_G[n:upper()..'_SOURCE']))() end
          end
          callbacks={};jobs={};jobId=0;pending={};members={}
          package.preload.event=function() return {
            listen=function(n,f) callbacks[n]=callbacks[n] or {};table.insert(callbacks[n],f) end,
            push=function() end} end
          local lg={status=function(id) return jobs[id] end}
          package.preload.logistics=function() return lg end
          wh={group=function() end,settled=function() return true end,
            add=function(n) members[n]={} end,
            scan=function(names)
              local ids={}
              for _,n in ipairs(names) do
                jobId=jobId+1;ids[#ids+1]=jobId
                jobs[jobId]={state='done',steps={{read=map.storage(n),size=27}}}
                pending[#pending+1]=jobId
              end
              return ids
            end}
          package.preload.warehouse=function() return wh end
          function complete()
            for _,id in ipairs(pending) do for _,f in ipairs(callbacks.logistics or {}) do f('logistics',id) end end
            pending={}
          end
          function trace() end
          map=require('map')
          function sample() peak=math.max(peak,collectgarbage('count')) end
          collectgarbage('collect');peak=collectgarbage('count');debug.sethook(sample,'',100)
        ''')
        program = builder.PROGRAM
        graph = program[program.index('local function node('):program.index("save('/etc/mes.cfg'")]
        lua.execute(graph)
        lua.execute('''
          graphPeak=peak;st=require('stations')
          collectgarbage('collect');commissionStart=collectgarbage('count');peak=commissionStart
        ''')
        commission = program[program.index('local stationNames={}'):program.index('wait(function() for _,n in ipairs(stationNames)')]
        lua.execute(commission)
        lua.execute('''
          complete();sample();debug.sethook()
          commissionPeak=peak;collectgarbage('collect');retained=collectgarbage('count')
          nodeCount=0;linkCount=0;storageCount=#map.storageNames()
          for _,n in ipairs(map.names()) do nodeCount=nodeCount+1;linkCount=linkCount+#map.links(n) end
          linkCount=linkCount/2
          for _,r in ipairs(st.list()) do assert(r.state=='ready',r.reason) end
          assert(#st.list()==14 and storageCount==64 and nodeCount==145 and linkCount==208)
        ''')
        result = dict(mode='before' if before else 'after', nodes=int(g.nodeCount), links=int(g.linkCount),
                    storages=int(g.storageCount), stations=14, commissioningReads=int(g.jobId),
                    graphPeakKiB=g.graphPeak, commissioningStartKiB=g.commissionStart,
                    commissioningPeakKiB=g.commissionPeak, retainedKiB=g.retained)
        for handle in handles:
            handle.close()
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scale-builder', type=Path, default=Path(
        'C:/Users/Conner/orca/workspaces/oc-robot-accelerator/lt-timing/build_native_scale.py'))
    parser.add_argument('--installation', type=Path, default=Path('C:/or/drone-install-IO1'))
    args = parser.parse_args()
    copied = args.output.parent / 'MAPSTORE-scale-builder.py'
    shutil.copyfile(args.scale_builder, copied)  # Only the read-only builder is copied.
    spec = importlib.util.spec_from_file_location('mapstore_scale_geometry', copied)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    with zipfile.ZipFile(args.installation / 'acquired/OpenComputers-1.8.9a.jar') as archive:
        serializer = archive.read('assets/opencomputers/loot/openos/lib/serialization.lua')
    result = dict(method='Lua 5.3 heap sampled every 100 instructions; host-backed HDD; exact SCALE geometry',
                  scope='map/store/stations; logistics and warehouse commissioning-read completions are headless',
                  repetitions=[measure(builder, serializer, before) for before in (True, False) for _ in range(3)])
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
