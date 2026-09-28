"""Compare two retained follow-up runs by label, including gate and action energy."""
import gzip
import json
from pathlib import Path
import sys

# Retained analyzer fixture exercises supervisor-failure propagation in comparison tests.
ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import compare

GATE_FIELDS = ('tick', 'worldTotalTime', 'serverTick', 'savePhase', 'debitPhase', 'x', 'y', 'z',
               'facing', 'energy', 'state', 'workerExecuting', 'inventoryCount', 'toolDamage',
               'toolItem', 'frontBlock', 'farBlock', 'queuedSignals', 'callbacksBeforeGate')


def load(label):
    records = json.loads((HERE / 'runs.json').read_text())
    record = next(item for item in records if item['label'] == label)
    with gzip.open(HERE / record['trace']['file'], 'rt', encoding='utf-8') as stream:
        rows = [json.loads(line) for line in stream]
    callbacks = [item for item in rows if item.get('kind') == 'callback']
    ticks = {item['tick']: item for item in rows if item.get('kind') == 'tick'}
    gate = next((item for item in rows if item.get('kind') == 'prepared_gate'), None)
    energies = [ticks.get(item['tick'], {}).get('energy') for item in callbacks]
    return record, rows, callbacks, gate, energies


def analyze(reference, candidate):
    a, rows_a, ac, ag, ae = load(reference)
    b, rows_b, bc, bg, be = load(candidate)
    report = compare.compare((a['result'], ac, a['supervisor']), (b['result'], bc, b['supervisor']))
    report['labels'] = [reference, candidate]
    report['actionEnergyAtFirstCallback'] = [ae[0] if ae else None, be[0] if be else None]
    report['actionEnergyAtLastCallback'] = [ae[-1] if ae else None, be[-1] if be else None]
    report['callbackEnergyEqual'] = bool(ae) and bool(be) and None not in ae + be and ae == be
    report['firstCallbackEnergyMismatch'] = next((dict(actionIndex=i, values=[ae[i] if i < len(ae) else None,
                                                                                         be[i] if i < len(be) else None])
                                                 for i in range(max(len(ae), len(be)))
                                                 if i >= len(ae) or i >= len(be) or ae[i] != be[i]), None)
    report['gateGameStateDifferences'] = ({key: [ag.get(key), bg.get(key)] for key in GATE_FIELDS
                                          if ag.get(key) != bg.get(key)} if ag and bg else None)
    report['gateGameStateComplete'] = bool(ag and bg and all(key in ag and key in bg for key in GATE_FIELDS))
    report['gateUptime'] = [gate.get('uptime') if gate else None for gate in (ag, bg)]
    report['gateHostCpuSeconds'] = [gate.get('hostCpuSeconds') if gate else None for gate in (ag, bg)]
    report['taskSeconds'] = [record['result'].get('taskElapsedNanos', 0) / 1e9 for record in (a, b)]
    report['saveEvents'] = [[item for item in rows if item.get('kind') == 'scheduler'
                              and item.get('boundary', '').startswith('save:')] for rows in (rows_a, rows_b)]
    report['scope'] += ' Prepared gate and callback-associated END energy are supplemental comparisons; neither establishes whole-world or cold-boot equivalence.'
    return report


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python evidence/fidelity/analyze.py REFERENCE_LABEL CANDIDATE_LABEL')
    print(json.dumps(analyze(sys.argv[1], sys.argv[2]), indent=2, sort_keys=True))
