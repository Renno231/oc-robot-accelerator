"""Run current stats over an R4 saved catalogue, without submitting native jobs."""
import argparse
import json
from pathlib import Path
from lupa.lua53 import LuaRuntime
from test_store import install_store


def summary(root):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SERIAL = (root / 'lib/serialization.lua').read_text()
    lua.execute('''
      function checkArg(n,v,...)
        for _,t in ipairs({...}) do if type(v)==t then return end end
        error('bad argument '..n)
      end
      package.preload.serialization=function() return assert(load(SERIAL))() end
    ''')
    install_store(lua)
    for name in ('warehouse.cfg', 'warehouse.db', 'warehouse.flight', 'warehouse.stacks', 'map.cfg'):
        p = root / 'etc' / name
        if p.exists():
            lua.globals().disk['/etc/' + name] = p.read_bytes()
    for name in ('warehouse', 'stats'):
        lua.globals()[name.upper()] = Path('drone-logistics/usr/lib/logistics/' + name + '.lua').read_text()
    lua.execute('''
      local ser=require('serialization')
      local cfg=assert(ser.unserialize(disk['/etc/map.cfg']))
      package.loaded["logistics.map"]={storage=function(n) return cfg.storages[n] end,
        storages=function() return cfg.storages end,node=function(n) return cfg.nodes[n] end,
        revision=function() return 0 end}
      READS,JOBS=0,0
      package.loaded.logistics={status=function() return nil end,
        job=function() JOBS=JOBS+1;error('unexpected native job') end}
      package.loaded.component={transposer={getAllStacks=function() READS=READS+1;error('unexpected read') end}}
      package.loaded.event={listen=function() end,push=function() end,timer=function() end}
      local db=require('logistics.store').open('/etc/warehouse.db','log'):load()
      TIME=0;for _,v in pairs(db) do TIME=math.max(TIME,v.time or 0) end
      package.loaded.computer={uptime=function() return TIME end}
      package.loaded["logistics.warehouse"]=assert(load(WAREHOUSE))()
      stats=assert(load(STATS))();resetCalls();RESULT=stats.summary()
      assert(READS==0 and JOBS==0 and not calls.read and not calls.write)
    ''')

    def convert(value):
        if hasattr(value, 'items'):
            items = list(value.items())
            if items and all(isinstance(k, int) for k, _ in items):
                return [convert(value[i]) for i in range(1, len(items) + 1)]
            return {str(k): convert(v) for k, v in items}
        return value

    result = convert(lua.globals().RESULT)
    result.update(root=str(root), uptime=lua.globals().TIME, reads=0, jobs=0)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path, help='Saved controller HDD with etc/warehouse.db')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = json.dumps(summary(args.root), indent=2)
    if args.output:
        args.output.write_text(text + '\n')
    else:
        print(text)
