"""Native OC-parts with either supported store format; diagnostics stay on host."""
import argparse
import json
from pathlib import Path
from examples.mes.build_fixtures import build_native, write_fixture


def build(root, variant):
    if variant not in ('log', 'files'): raise ValueError('unknown store format')
    path = build_native(Path(root) / 'fixture', 'ocparts')
    (path.parent / 'program/etc/store.cfg').write_text('{variant="' + variant + '"}\n')
    value = json.loads(path.read_text());value['id'] = 'ocparts-' + variant
    return write_fixture(path, value)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--variant', choices=('log', 'files'), required=True)
    args = parser.parse_args()
    print(build(args.root, args.variant))
