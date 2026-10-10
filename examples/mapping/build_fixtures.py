"""Generate the two native mapping layouts and deploy canonical Lua files."""
import copy
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[2]
base=json.loads((ROOT/'examples/logistics/transfer/scenario.json').read_text())
for case in ('service','actions'):
    directory=ROOT/'examples/mapping'/case
    spec=copy.deepcopy(base);spec['id']='mapping-'+case
    spec['secondComputer']=copy.deepcopy(spec['computer'])
    spec['secondComputer']['position']=[-3,65,6]
    spec['secondComputer']['program']['directory']='client'
    # Independent finite native networks, four charged capacitors per case.
    spec['blocks']=[b for b in spec['blocks'] if b['position'][0]>=0]
    for z in (2,6):
        for x,y in ((-4,65),(-4,66),(-3,66),(-2,66)):
            spec['blocks'].append(dict(position=[x,y,z],block='opencomputers:capacitor',energy=1600))
    if case=='service':
        spec['drones']=[];spec['containers']=[];spec['blocks']=[b for b in spec['blocks'] if b['position'][0]<0]
        spec['expect']={}
    else:
        spec['containers']=spec['containers'][:1];spec['containers'][0]['slots']=[]
        spec['blocks'].append(dict(position=[4,65,2],block='minecraft:stone'))
        spec['expect']={'drones':[dict(index=0,blockPosition=[0,65,0],running=True,inventory=[])]}
        directory.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/'drone-logistics/drone/loader.lua',directory/'loader.lua')
    for target in ('program','client'):
        program=directory/target;program.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/'examples/mapping'/('controller.lua' if target=='program' else 'client.lua'),program/'main.lua')
        for path in ('lib/map.lua','lib/mapclient.lua','bin/mapd.lua','bin/mapclient.lua'):
            destination=program/path;destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/'drone-logistics'/path,destination)
        if case=='actions' and target=='program':
            for path in ('lib/logistics.lua','lib/cbor.lua','lib/store.lua','drone/agent.lua'):
                destination=program/path;destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/'drone-logistics'/path,destination)
        (program/'case.lua').write_text('return "'+case+'"\n')
    (directory/'scenario.json').write_text(json.dumps(spec,indent=2)+'\n')
