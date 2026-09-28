"""Compare bounded robot-run evidence without hiding startup/resource differences."""
import argparse
import json
from pathlib import Path

OBSERVATIONS = ('status', 'reason', 'ticks', 'x', 'y', 'z', 'facing', 'energy', 'uptime', 'state',
                'inventoryCount', 'toolDamage', 'toolItem', 'initialTool', 'finalTool', 'firmwareResult',
                'executionDelayMillis', 'laps', 'traceEnabled', 'preparedStart', 'workerExecuting',
                'worldTotalTime', 'serverTick', 'savePhase', 'debitPhase', 'frontBlock', 'farBlock')


def load(root):
    root = Path(root)
    def bounded(name, limit):
        with (root / name).open('rb') as source:
            content = source.read(limit + 1)
        if len(content) > limit: raise ValueError(name + ' byte bound exceeded')
        return content
    result = json.loads(bounded('result.json', 1024 * 1024))
    supervisor = json.loads(bounded('supervisor.json', 1024 * 1024))
    trace = [json.loads(line) for line in bounded('trace.ndjson', 4 * 1024 * 1024).splitlines()]
    return result, [event for event in trace if event.get('kind') == 'callback'], supervisor


def compare(reference, candidate):
    a, ac, ar = reference; b, bc, br = candidate
    def tuples(calls): return [(c['method'], c['arguments'], c['results']) for c in calls]
    def deltas(calls): return [right['tick'] - left['tick'] for left, right in zip(calls, calls[1:])]
    at, bt = tuples(ac), tuples(bc)
    ad, bd = deltas(ac), deltas(bc)
    cadence_index = next((i for i in range(max(len(ad), len(bd)))
                          if i >= len(ad) or i >= len(bd) or ad[i] != bd[i]), None)
    first_cadence = None
    if cadence_index is not None:
        i = cadence_index
        first_cadence = dict(actionIndex=i + 1,
                             intervals=[values[i] if i < len(values) else None for values in (ad, bd)],
                             ticks=[[calls[i]['tick'], calls[i + 1]['tick']] if i + 1 < len(calls) else None
                                    for calls in (ac, bc)],
                             methods=[[calls[i]['method'], calls[i + 1]['method']] if i + 1 < len(calls) else None
                                      for calls in (ac, bc)])
    mismatch = next((i for i in range(max(len(at), len(bt)))
                     if i >= len(at) or i >= len(bt) or at[i] != bt[i]), None)
    profiles = {key: [ar['sha256'].get(key), br['sha256'].get(key)]
                for key in sorted(set(ar['sha256']) | set(br['sha256']))
                if ar['sha256'].get(key) != br['sha256'].get(key)}
    observations = {key: [a.get(key), b.get(key)] for key in OBSERVATIONS if a.get(key) != b.get(key)}
    passed = a.get('status') == b.get('status') == ar.get('status') == br.get('status') == 'passed'
    tuples_equal = bool(ac) and bool(bc) and at == bt
    cadence_equal = bool(ac) and bool(bc) and ad == bd
    absolute_ticks_equal = bool(ac) and bool(bc) and [c['tick'] for c in ac] == [c['tick'] for c in bc]
    return dict(bothPassed=passed, callbackCounts=[len(ac), len(bc)], callbackTuplesEqual=tuples_equal,
                firstCallbackMismatch=mismatch, interActionTicksEqual=cadence_equal,
                firstInterActionMismatch=first_cadence,
                actionSpanTicks=[calls[-1]['tick'] - calls[0]['tick'] if calls else None for calls in (ac, bc)],
                absoluteActionTicksEqual=absolute_ticks_equal,
                firstActionTick=[ac[0]['tick'] if ac else None, bc[0]['tick'] if bc else None],
                lastActionTick=[ac[-1]['tick'] if ac else None, bc[-1]['tick'] if bc else None],
                fixtureSeconds=[a.get('elapsedNanos', 0) / 1e9, b.get('elapsedNanos', 0) / 1e9],
                actionSpanSeconds=[a.get('actionSpanNanos', 0) / 1e9, b.get('actionSpanNanos', 0) / 1e9],
                totalWallSeconds=[ar['elapsed_wall_seconds'], br['elapsed_wall_seconds']],
                observationDifferences=observations, profileDifferences=profiles,
                selectedObservationsMatch=passed and tuples_equal and absolute_ticks_equal and not observations and not profiles,
                scope='Callback tuples/timing and listed final observations only; tick-state streams and unobserved world state are not compared. No universal parity inference.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference'); parser.add_argument('candidate')
    args = parser.parse_args()
    print(json.dumps(compare(load(args.reference), load(args.candidate)), indent=2, sort_keys=True))


if __name__ == '__main__': main()
