"""Print a run's controller heap censuses: a timeline, then who holds memory at one census."""
import argparse
import json
from pathlib import Path


def kb(n):
    return '%.0f' % (n / 1024)


def clock(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return '%d:%02d:%02d' % (h, m, s) if h else '%d:%02d' % (m, s)


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def timeline(censuses):
    print('time     why    free KB  live KB  garbage KB  walked/heap KB  pause ms')
    for c in censuses:
        if 'error' in c or 'walkedBytes' not in c['census']:
            print('%-8s %-6s %s' % (clock(c.get('gameSeconds', 0)), c.get('reason', ''),
                                    'error: ' + c['error'] if 'error' in c else 'OpenOS not booted yet'))
            continue
        walked = c['census']['walkedBytes']
        print('%-8s %-6s %7s  %7s  %10s  %6s/%-7s %8.0f' % (
            clock(c['gameSeconds']), c['reason'], kb(c['freeBytes']), kb(c['usedBytes']),
            kb(c['garbageBytes']), kb(walked), kb(c['heapBytes']), c['wallMillis']))


def parts(top, depth):
    """Each part of at least 1 KB with its own biggest parts below it."""
    for t in top:
        if t['bytes'] >= 1024:
            print('%s%-*s %6s KB' % ('    ' * depth, 36 - 4 * depth, t['key'], kb(t['bytes'])))
            parts(t.get('fields', [])[:3], depth + 1)


def breakdown(c, limit):
    census = c['census']
    print('\nAt %s (%s): %s KB free of %s KB; %s KB live, %s KB garbage' % (
        clock(c['gameSeconds']), c['reason'], kb(c['freeBytes']), kb(c['totalBytes']),
        kb(c['usedBytes']), kb(c['garbageBytes'])))
    print('module                         KB   code KB')
    for m in census['modules'][:limit]:
        print('%-28s %6s  %8s' % (m['name'], kb(m['bytes']), kb(m['codeBytes'])))
        for child in m['children'][:6]:
            if child['bytes'] < 2048:
                break
            print('    %-30s %6s KB  %5d entries' % (child['name'], kb(child['bytes']), child['entries']))
            parts(child['top'][:3], 2)
    print('%-28s %6s' % ('programs\' globals', kb(census['globalsBytes'])))
    print('%-28s %6s' % ('kernel and the rest', kb(census['kernelBytes'])))
    code = sum(m['codeBytes'] for m in census['modules'])
    print('\nAll modules: %s KB code, %s KB data' % (kb(code), kb(sum(m['bytes'] for m in census['modules']) - code)))
    if 'codeBySource' in census:
        # A module's code above counts what it reached first; this counts each file's own.
        print('\nfile                                code KB')
        for s in census['codeBySource'][:limit]:
            print('%-34s %8s' % (s['source'].lstrip('=@'), kb(s['bytes'])))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('census', type=Path, help='heap-census.ndjson from run_mes_scenarios.py --heap-census')
    parser.add_argument('--at', type=int, help='census index to break down (default: lowest free memory)')
    parser.add_argument('--modules', type=int, default=15)
    args = parser.parse_args()
    censuses = rows(args.census)
    timeline(censuses)
    good = [c for c in censuses if 'walkedBytes' in c.get('census', {})]
    if good:
        breakdown(censuses[args.at] if args.at is not None else min(good, key=lambda c: c['freeBytes']), args.modules)
