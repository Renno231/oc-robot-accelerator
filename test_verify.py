"""Contract checks for the developer verification entrypoint, without game boots."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import verify


class VerifyTest(unittest.TestCase):
    def test_source_plan_owns_existing_checks(self):
        args = verify.parser().parse_args(['--output', 'out', '--java-home', 'jdk'])
        steps = verify.steps(args, Path('out'))
        labels = [step[0] for step in steps]
        self.assertEqual(labels, ['python', 'java-build', 'viewer-unit', 'package', 'package-repeat'])
        self.assertIn('bootstrap.py', ' '.join(steps[1][1]))
        self.assertIn('--java-home', steps[1][1])

    def test_missing_profile_inputs_fail_before_output_creation(self):
        for check in ('source', 'runtime', 'package', 'viewer'):
            args = verify.parser().parse_args(['--checks', check, '--output', 'out'])
            with self.assertRaises(ValueError):
                verify.steps(args, Path('out'))

    def test_existing_output_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileExistsError):
                verify.main(['--output', directory, '--java-home', 'jdk'])

    def test_failed_step_preserves_command_and_failure_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'verify'
            with mock.patch.object(verify, 'steps', return_value=[('broken', ['fake'], 2)]), \
                 mock.patch.object(verify, 'run_checked', side_effect=RuntimeError('intended failure')):
                self.assertEqual(verify.main(['--output', str(output)]), 1)
            import json
            report = json.loads((output / 'verification.json').read_text())
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['steps'][0]['command'], ['fake'])
            self.assertIn('intended failure', report['error'])


if __name__ == '__main__':
    unittest.main()
