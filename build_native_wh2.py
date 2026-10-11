"""WH2 isolated partial export plus real ALERTS; optional baseline agent."""
import argparse
import json
from pathlib import Path
import subprocess
from build_native_alerts import build as alerts_build
from supervisor import NO_WINDOW


def build(root, baseline=False):
    path = alerts_build(root, 'io')
    entry = path.parent / 'program/native-main.lua'
    program = entry.read_text().replace('local result={jobs={},', 'local result={ready=lg.drones(),jobs={},')
    if not baseline:
        program = program.replace("ic.fetch(coal,256,'out1')", "ic.fetch(coal,128,'out1')")
        program = program.replace("wh.count(coal)==0 and count('out1')==256", "wh.count(coal)==128 and count('out1')==128")
        program = program.replace("assert(ic.importNow('in2'))", """result.partialExport={count=wh.count(coal),catalogue=wh.contents('stock'),
 stats=require('stats').summary(),alerts=require('mes_alerts').list(),job=lg.status(recoveryJob)}
assert(result.partialExport.count==128 and result.partialExport.catalogue.freeSlots==2)
assert(result.partialExport.stats.usedSlots==25 and result.partialExport.stats.fill<.93)
assert(ic.importNow('in2'))""")
        program = program.replace('wh.count(coal)==104', 'wh.count(coal)==232')
        value = json.loads(path.read_text())
        for container in value['expect']['containers']:
            if container['position'] == [0, 64, 8]:
                container['slots'] = container['slots'][:23] + [
                    {'slot': s, 'item': 'minecraft:coal', 'count': 40 if s == 25 else 64}
                    for s in range(24, 28)]
            elif container['position'] == [10, 64, 8]:
                container['slots'] = [{'slot': s, 'item': 'minecraft:coal', 'count': 64 if s <= 2 else 0}
                                      for s in range(1, 5)]
        value['id'] = 'io-flow-wh2-partial'
        path.write_text(json.dumps(value, indent=2) + '\n')
    else:
        agent = path.parent / 'program/drone/agent.lua'
        agent.write_bytes(subprocess.check_output(['git', 'show', '1f666d0:drone-logistics/drone/agent.lua'],
                                                 creationflags=NO_WINDOW))
    entry.write_text(program)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    print(build(args.root, args.baseline))
