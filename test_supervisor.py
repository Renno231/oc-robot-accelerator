"""Process-boundary safety tests; fake Java is a Python subprocess, never Minecraft."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("robot_supervisor", HERE / "supervisor.py")
try:
    supervisor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(supervisor)
except FileNotFoundError:
    supervisor = None

FIXTURE = '''import json, pathlib, sys, time
args = sys.argv[1:]
root = pathlib.Path(next(a.split('=', 1)[1] for a in args if a.startswith('-Drobotspike.root=')))
mode = next(a.split('=', 1)[1] for a in args if a.startswith('-Drobotspike.mode='))
scenario = (root / 'scenario.txt').read_text().strip()
if scenario == 'timeout':
    time.sleep(20)
elif scenario == 'trace':
    (root / 'trace.ndjson').write_bytes(b'x' * (32 * 1024 * 1024 + 1))
    time.sleep(20)
elif scenario in ('coverage_status', 'coverage_temporary'):
    name = 'observations-status.json' if scenario == 'coverage_status' else '.observations-status.json.tmp'
    (root / name).write_bytes(b'x' * 65537)
    time.sleep(20)
elif scenario == 'oversized_result':
    (root / 'result.json').write_bytes(b'x' * (1024 * 1024 + 1))
elif scenario == 'output':
    while True:
        print('x' * 8192, flush=True)
else:
    if scenario not in ('missing', 'oversized_result'):
        data = {'status': 'failed' if scenario == 'failed' else 'passed', 'reason': 'fixture',
                'mode': mode, 'ticks': 2, 'elapsedNanos': 200}
        (root / 'result.json').write_text('not json' if scenario == 'malformed' else json.dumps(data))
    print('fixture stdout', flush=True)
    print('fixture stderr', file=sys.stderr, flush=True)
    sys.exit(3 if scenario == 'nonzero' else 0)
'''


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.template = self.base / 'template'
        self.output = self.base / 'runs'
        self.template.mkdir()
        self.output.mkdir()
        for name in ('forge-1.12.2-14.23.5.2860.jar', 'minecraft_server.1.12.2.jar',
                     'libraries/sample.jar', 'mods/OpenComputers.jar', 'config/opencomputers/settings.conf'):
            path = self.template / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture')
        (self.template / 'eula.txt').write_text('eula=true\n')
        (self.template / 'scenario.txt').write_text('success')
        self.jar = self.base / 'robot-spike.jar'
        self.jar.write_bytes(b'control')
        fixture_hash = hashlib.sha256(b'fixture').hexdigest()
        pins = {name: fixture_hash for name in supervisor.PINNED}
        patcher = mock.patch.object(supervisor, 'PINNED', pins)
        patcher.start()
        self.addCleanup(patcher.stop)
        fixture = self.base / 'fixture.py'
        fixture.write_text(FIXTURE)
        if os.name == 'nt':
            self.java = self.base / 'java.cmd'
            self.java.write_text('@echo off\n"%s" "%s" %%*\n' % (sys.executable, fixture))
        else:
            self.java = self.base / 'java'
            self.java.write_text('#!%s\n%s' % (sys.executable, FIXTURE))
            self.java.chmod(0o755)

    def invoke(self, scenario='success', **changes):
        (self.template / 'scenario.txt').write_text(scenario)
        args = ['--template', str(changes.get('template', self.template)),
                '--output-root', str(self.output), '--control-jar', str(changes.get('control_jar', self.jar)),
                '--java', str(self.java), '--mode', 'baseline', '--ticks', '10',
                '--timeout', str(changes.get('timeout', 4))]
        before = set(self.output.iterdir())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = supervisor.main(args)
        self.last_output = output.getvalue()
        runs = list(self.output.iterdir())
        created = set(runs) - before
        return code, runs, json.loads((next(iter(created)) / 'supervisor.json').read_text()) if created else None

    @unittest.skipUnless(os.name == 'nt', 'Windows legacy Java path policy')
    def test_long_windows_destination_reports_short_root_remedy_before_copy(self):
        import time
        root = self.output / ('x' * 180)
        # The root itself is deliberately not created; validation precedes any copy.
        with self.assertRaisesRegex(ValueError, 'shorter.*root'):
            supervisor._prepare(self.template, self.jar, root, time.monotonic()+5)
        self.assertFalse(root.exists())

    def test_success_and_unique_isolated_runs(self):
        code, runs, report = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(len(runs), 1)
        outcome = json.loads(self.last_output.strip())
        self.assertEqual(self.last_output.count('\n'), 1)
        self.assertEqual(outcome, {'run_directory': str(runs[0]), 'status': 'passed',
                                   'reason': report['reason']})
        self.assertIn('control/robot-spike.jar', report['sha256'])
        self.assertIn('template/config/opencomputers/settings.conf', report['sha256'])
        self.assertIn('-Dfml.disableVersionCheck=true', report['command'])
        self.assertEqual(report['command'][0], str(self.java.resolve()))
        self.assertEqual(report['profile'], 'base')
        self.assertTrue((runs[0] / 'stdout.log').exists())
        properties = (runs[0] / 'server.properties').read_text()
        for entry in ('server-ip=127.0.0.1', 'server-port=0', 'enable-rcon=false',
                      'enable-query=false', 'online-mode=true', 'snooper-enabled=false',
                      'level-type=FLAT', 'difficulty=0'):
            self.assertIn(entry, properties)
        code, runs, report = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(len(runs), 2)
        self.assertNotEqual(runs[0], runs[1])

    def test_pinned_artifact_mismatch_prevents_launch(self):
        (self.template / 'mods/OpenComputers.jar').write_bytes(b'wrong binary')
        with mock.patch.object(supervisor.subprocess, 'Popen') as launch:
            code, _, report = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertIn('base artifact SHA-256 mismatch', report['reason'])
        launch.assert_not_called()

    def test_extra_mod_is_extended_profile(self):
        (self.template / 'mods/extra.jar').write_bytes(b'extra')
        code, _, report = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(report['profile'], 'extended')
        self.assertIn('template/mods/extra.jar', report['sha256'])

    def test_growing_control_jar_rejected_before_launch(self):
        original = Path.open
        jar = self.jar
        def open_with_growth(path, *args, **kwargs):
            if path == jar and args and args[0] == 'rb':
                return io.BytesIO(b'control expanded after stat')
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, 'open', open_with_growth), mock.patch.object(
                supervisor.subprocess, 'Popen') as launch:
            code, _, report = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertIn('control jar changed', report['reason'])
        launch.assert_not_called()

    def test_result_and_exit_failures(self):
        for scenario in ('missing', 'malformed', 'failed', 'nonzero'):
            with self.subTest(scenario=scenario):
                code, _, report = self.invoke(scenario)
                self.assertNotEqual(code, 0)
                self.assertEqual(report['status'], 'failed')
                self.assertTrue(report['reason'])
                if scenario == 'failed': self.assertIn('fixture', report['reason'])
                outcome = json.loads(self.last_output.strip())
                self.assertEqual(outcome['status'], 'failed')
                self.assertEqual(outcome['reason'], report['reason'])

    def test_timeout_cleans_up(self):
        code, _, report = self.invoke('timeout', timeout=1)
        self.assertNotEqual(code, 0)
        self.assertIn('timeout', report['reason'])
        self.assertIsNotNone(report['return_code'])

    def test_oversized_output_fails_without_pipe_deadlock(self):
        code, runs, report = self.invoke('output')
        self.assertNotEqual(code, 0)
        self.assertIn('output', report['reason'])
        self.assertLessEqual((runs[-1] / 'stdout.log').stat().st_size, supervisor.LOG_LIMIT)

    def test_trace_and_result_bounds(self):
        code, _, report = self.invoke('trace')
        self.assertNotEqual(code, 0)
        self.assertIn('trace', report['reason'])
        code, _, report = self.invoke('oversized_result')
        self.assertNotEqual(code, 0)
        self.assertIn('1MiB', report['reason'])

    def test_coverage_publication_files_are_bounded(self):
        for case, name in [('coverage_status','observations-status.json'),
                           ('coverage_temporary','.observations-status.json.tmp')]:
            with self.subTest(case=case):
                code, _, report = self.invoke(case)
                self.assertNotEqual(code, 0)
                self.assertIn(name + ' byte bound exceeded', report['reason'])
                self.assertTrue(report['cleanup_ok'])

    def test_copy_cap_and_path_escapes(self):
        with (self.template / 'huge').open('wb') as file:
            file.truncate(supervisor.COPY_BYTES_LIMIT + 1)
        code, runs, report = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertEqual(report['status'], 'failed')
        (self.template / 'huge').unlink()
        escape = self.base / 'external'
        escape.write_bytes(b'secret')
        try:
            (self.template / 'libraries' / 'escape').symlink_to(escape)
            linkjar = self.base / 'linked.jar'
            linkjar.symlink_to(self.jar)
        except (OSError, NotImplementedError):
            return  # Windows symlink privilege may be unavailable; copy-cap assertion still ran.
        code, _, report = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertIn('link', report['reason'].lower())
        (self.template / 'libraries' / 'escape').unlink()
        code, _, report = self.invoke(control_jar=linkjar)
        self.assertNotEqual(code, 0)
        self.assertIn('link', report['reason'].lower())

    def test_live_inventory_tolerates_atomic_rename_only(self):
        # os.walk observed this name, then Minecraft renamed it before lstat.
        walk = [(str(self.template), [], ['level.dat'])]
        with mock.patch.object(supervisor.os, 'walk', return_value=walk):
            with self.assertRaises(FileNotFoundError):
                supervisor._inventory(self.template, 100, 10)
            self.assertEqual(supervisor._inventory(self.template, 100, 10, live=True), [])
        with mock.patch.object(supervisor.os, 'walk', return_value=walk), mock.patch.object(
                Path, 'lstat', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                supervisor._inventory(self.template, 100, 10, live=True)

    def test_windows_skip_taskkill_for_exited_process(self):
        process = mock.Mock(pid=12345)
        process.poll.return_value = 0
        with mock.patch.object(supervisor.os, 'name', 'nt'), mock.patch.object(
                supervisor.subprocess, 'run') as taskkill:
            supervisor._stop_tree(process)
        taskkill.assert_not_called()
        process.wait.assert_called_once_with(timeout=3)

    def test_reject_template_output_overlap(self):
        args = ['--template', str(self.template), '--output-root', str(self.template),
                '--control-jar', str(self.jar), '--java', str(self.java), '--mode', 'baseline']
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertNotEqual(supervisor.main(args), 0)
        self.assertEqual(json.loads(output.getvalue())['run_directory'], None)

    def test_requires_actual_oc_config_path(self):
        settings = self.template / 'config/opencomputers/settings.conf'
        settings.rename(self.template / 'config/opencomputers.cfg')
        code, _, report = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertIn('incomplete prepared server template', report['reason'])

    def test_invalid_eula_and_parameters(self):
        (self.template / 'eula.txt').write_text('eula=false\n')
        code, _, report = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertIn('eula', report['reason'].lower())
        with self.assertRaises(SystemExit) as rejected:
            supervisor.main(['--template', str(self.template), '--output-root', str(self.output),
                             '--control-jar', str(self.jar), '--java', str(self.java),
                             '--mode', 'baseline', '--ticks', '10001'])
        self.assertEqual(rejected.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
