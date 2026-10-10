"""One isolated R4 native submission, with durable command/result evidence."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from build_native_restarts import build, CASES
from supervisor import NO_WINDOW


def run(args):
    if args.case.startswith('ocparts-'):
        from build_native_store_measurements import build as measurement
        path = measurement(args.root, args.case.split('-', 1)[1])
    else:
        path = build(args.root, args.case)
    command = [sys.executable, 'runner.py', 'run', str(path), '--installation',
               str(args.installation), '--jobs-root', str(args.jobs_root)]
    with (args.root / 'native-command.log').open('w') as output:
        completed = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=NO_WINDOW)
    text = (args.root / 'native-command.log').read_text()
    state = json.loads(text.strip().splitlines()[-1])
    summary = {'case': args.case, 'command': command, 'commandExit': completed.returncode,
               'root': str(args.root), 'jobsRoot': str(args.jobs_root), 'state': state}
    (args.root / 'run.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)
    return completed.returncode


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--jobs-root', type=Path, required=True)
    parser.add_argument('--case', choices=CASES + ('baseline', 'ocparts-log', 'ocparts-files'), required=True)
    parser.add_argument('--installation', type=Path, default=Path('C:/or/drone-install-T11'))
    sys.exit(run(parser.parse_args()))
