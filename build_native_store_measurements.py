"""ocparts store measurements using the real store and public component counter."""
import argparse
import json
from pathlib import Path
from build_machine_comparisons import prepare


MEASURE = '''
-- Measurement-only wrappers around the canonical store; no alternate encoder.
local counter=assert(package.loaded.runner_component_calls)
local measurement={variant=storeVariant,stores={},peakUsedBytesDuringSaves=0,
  peakMethod='sampled before/after saves, CBOR encode and filesystem invoke'}
package.loaded.runner_store_measurements=measurement
local saving=0
local function sample()
  if saving>0 then measurement.peakUsedBytesDuringSaves=math.max(measurement.peakUsedBytesDuringSaves,
    computer.totalMemory()-computer.freeMemory()) end
end
local cbor=require('cbor')
local encode=cbor.encode
cbor.encode=function(...)
  sample();local bytes=encode(...);sample();return bytes
end
local invoke=component.invoke
component.invoke=function(address,method,...)
  if component.type(address)=='filesystem' then sample() end
  local result=table.pack(invoke(address,method,...))
  if component.type(address)=='filesystem' then sample() end
  return table.unpack(result,1,result.n)
end
local store=require('store')
local open=store.open
local handles={}
store.open=function(path,variant)
  local handle=open(path,variant)
  local row={variant=variant or storeVariant,saves=0,startupRestoreSeconds=0}
  measurement.stores[path]=row;handles[path]=handle
  for _,name in ipairs({'put','delete','flush'}) do
    local operation=handle[name]
    handle[name]=function(self,...)
      saving=saving+1;sample()
      local values=table.pack(operation(self,...))
      sample();saving=saving-1;row.saves=row.saves+1
      return table.unpack(values,1,values.n)
    end
  end
  local load=handle.load
  handle.load=function(self,...)
    local start=computer.uptime();local values=table.pack(load(self,...))
    row.startupRestoreSeconds=row.startupRestoreSeconds+computer.uptime()-start
    return table.unpack(values,1,values.n)
  end
  return handle
end
local measurementBefore=counter.snapshot()
local function finishStoreMeasurements()
  local after=counter.snapshot()
  measurement.componentCalls=counter.delta(measurementBefore,after)
  measurement.filesystemCalls=measurement.componentCalls.byType.filesystem or 0
  measurement.restoreSeconds=0
  for path,handle in pairs(handles) do
    handle:flush()
    local beforeCalls=counter.snapshot();local start=computer.uptime()
    handle:load()
    local seconds=computer.uptime()-start
    local row=measurement.stores[path]
    row.restoreSeconds=seconds
    row.restoreFilesystemCalls=counter.delta(beforeCalls,counter.snapshot()).byType.filesystem or 0
    measurement.restoreSeconds=measurement.restoreSeconds+seconds
  end
end
'''


def build(root, variant):
    path = prepare('examples/mes/ocparts', Path(root) / 'fixture', 'coordinated')
    main = path.parent / 'program/native-main.lua'
    text = main.read_text().replace("{'map','logistics','warehouse'}",
                                    "{'cbor','store','map','logistics','warehouse'}")
    marker = "local lg=require('logistics');local wh=require('warehouse');local mes=require('mes')"
    install_config = "local storeVariant='" + variant + "'\n" + '''
local storeCfg=assert(io.open('/etc/store.cfg','w'))
assert(storeCfg:write(serialization.serialize({variant=storeVariant},false)));storeCfg:close()
'''
    assert marker in text
    text = text.replace(marker, install_config + MEASURE + '\n' + marker, 1)
    main.write_text(text + '\nfinishStoreMeasurements()\n')
    value = json.loads(path.read_text())
    value['id'] = 'r4-ocparts-' + variant
    assert len(value['drones']) >= 6
    path.write_text(json.dumps(value, indent=2) + '\n')
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--variant', choices=('log', 'files'), required=True)
    args = parser.parse_args()
    print(build(args.root, args.variant))
