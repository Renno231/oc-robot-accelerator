"""Prepare isolated mode variants; never edit the shipped acceptance fixtures."""
import argparse
import json
from pathlib import Path
import shutil


def prepare(source,destination,mode,observe=True):
    source=Path(source);destination=Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    shutil.copytree(source,destination)
    path=destination/'scenario.json'
    value=json.loads(path.read_text())
    value.setdefault('execution',{})['mode']=mode
    controller=value.get('computer',value.get('controller'))
    if observe and controller is not None:
        program=destination/controller['program']['directory']
        entry=program/controller['program'].get('entry','main.lua')
        entry.rename(program/'native-main.lua')
        entry.write_text(Path(__file__).with_name('machine_evidence.lua').read_text())
        shutil.copyfile(Path(__file__).with_name('machine_component_counter.lua'),
                        program/'component-counter.lua')
    path.write_text(json.dumps(value,indent=2)+'\n')
    return path


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('source',type=Path);parser.add_argument('destination',type=Path)
    parser.add_argument('--mode',choices=('baseline','coordinated'),required=True)
    args=parser.parse_args();print(prepare(args.source,args.destination,args.mode))
