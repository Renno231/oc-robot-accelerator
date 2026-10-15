"""Bind this accelerator checkout to the OC-Utilities application sources."""
import argparse
import os
from pathlib import Path
import subprocess


def bind(root, sources):
    pairs = [(root / local, sources.resolve() / canonical) for local, canonical in
             [('craftsystem', 'craftsystemv4_mes'), ('drone-logistics', 'drone-logistics')]]
    for link, target in pairs:
        if not target.is_dir():
            raise ValueError('Missing source directory: ' + str(target))
        if os.path.lexists(link) and link.resolve() != target:
            raise ValueError('Existing path preserved; move it before binding: ' + str(link))
    for link, target in pairs:
        if os.path.lexists(link):
            continue
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                           check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            link.symlink_to(target, target_is_directory=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', type=Path, help='OC-Utilities checkout')
    bind(Path(__file__).resolve().parent, parser.parse_args().sources)
