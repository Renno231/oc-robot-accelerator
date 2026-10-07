"""Generate native hallway/pillar layouts from the same finite-power fixture."""
import copy
import json
from pathlib import Path
import shutil

def build():
    template=json.loads(Path('examples/logistics/steps/scenario.json').read_text())
    for obstacle in (False,True):
        case='obstacle-room' if obstacle else 'storage-room'
        root=Path('examples/logistics')/case
        (root/'program').mkdir(parents=True,exist_ok=True)
        value=copy.deepcopy(template);value['id']='logistics-'+case
        value['world']={'region':{'min':[-6,62,-2],'max':[10,71,11]},'blocks':[
            {'min':[-6,62,-2],'max':[10,71,11],'block':'minecraft:air'},
            {'min':[-6,62,-2],'max':[10,63,11],'block':'minecraft:stone'}]}
        value['computer']['position']=[-4,65,2]
        value['drones'][0]['position']=[-2,65,2];value['drones'][1]['position']=[-2,65,5]
        value['blocks']=[]
        for z in (2,5):
            value['blocks'] += [ {'position':[-2,64,z],'block':'opencomputers:charger','properties':{'facing':'north'}},
                {'position':[-1,64,z],'block':'opencomputers:capacitor','energy':1600},
                {'position':[-2,63,z],'block':'minecraft:redstone_block'} ]
            for x,dz in ((-3,0),(-2,-1),(-2,1)):
                value['blocks'].append({'position':[x,64,z+dz],'block':'opencomputers:capacitor','energy':1600})
        for y in (65,66):
            for z in (2,3): value['blocks'].append({'position':[-5,y,z],'block':'opencomputers:capacitor','energy':1600})
        if obstacle: value['blocks'].append({'position':[3,65,4],'block':'minecraft:stone'})
        if obstacle:
            value['world']['blocks'].append({'min':[3,64,4],'max':[3,68,6],'block':'minecraft:stone'})
        value['containers']=[]
        w,h=(7,7) if obstacle else (8,4)
        for x in range(w):
            for y in range(h):
                if obstacle and x==3 and 2<=y<=4: continue
                for wall in ((0,) if obstacle else (1,3)):
                    position=[x,64,2+y] if obstacle else [x,65+y,wall]
                    slots=[]
                    if x==0 and y in ((0,h-1) if obstacle else (0,2,h-1)) and (obstacle or wall==1):
                        slots=[{'slot':i,'item':'minecraft:iron_ingot','count':64} for i in range(1,12)]
                    value['containers'].append({'position':position,'block':'minecraft:chest','properties':{} if obstacle else {'facing':'south' if wall==1 else 'north'},'slots':slots})
        value['expect']={'drones':[{'index':i,'blockPosition':[-2,65,z],'running':True} for i,z in enumerate((2,5))]}
        value['execution']['maxTicks']=18000;value['execution']['timeoutSeconds']=1000
        value['observations']={'everyTicks':1}
        (root/'scenario.json').write_text(json.dumps(value,indent=2)+'\n')
        (root/'program/main.lua').write_text("return require('room')("+('true' if obstacle else 'false')+")\n")
        shutil.copyfile('examples/logistics/room.lua',root/'program/room.lua')
        shutil.copyfile('examples/logistics/map-geometry-tests.lua',root/'program/map-geometry-tests.lua')

if __name__=='__main__': build()
