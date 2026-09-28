import unittest
from unittest.mock import patch
import importlib.util
from pathlib import Path
import compare


class CompareTest(unittest.TestCase):
    def sample(self, offset=0):
        result = dict(status='passed', mode='baseline', ticks=10 + offset, elapsedNanos=100,
                      actionSpanNanos=50, x=0, y=65, z=0, energy=100, state='Stopped', toolDamage=1)
        calls = [dict(kind='callback', method='move', arguments=[3], results=[True], tick=2 + offset),
                 dict(kind='callback', method='move', arguments=[0], results=[None, 'solid'], tick=8 + offset)]
        return result, calls, dict(status='passed', elapsed_wall_seconds=1, sha256={'template/mods/OpenComputers.jar': 'a'})

    def test_startup_offset_not_hidden_and_resources_not_normalized(self):
        a = self.sample(); b = self.sample(5); b[0]['energy'] = 90
        report = compare.compare(a, b)
        self.assertTrue(report['callbackTuplesEqual'])
        self.assertTrue(report['interActionTicksEqual'])
        self.assertEqual([2, 7], report['firstActionTick'])
        self.assertEqual([100, 90], report['observationDifferences']['energy'])
        self.assertFalse(report['selectedObservationsMatch'])
        self.assertFalse(report['absoluteActionTicksEqual'])

    def test_return_shape_and_cadence_difference_detected(self):
        a = self.sample(); b = self.sample(); b[1][1]['results'] = [False, 'solid']; b[1][1]['tick'] += 1
        report = compare.compare(a, b)
        self.assertFalse(report['callbackTuplesEqual'])
        self.assertFalse(report['interActionTicksEqual'])
        self.assertEqual(1, report['firstCallbackMismatch'])

    def test_first_cadence_divergence_includes_both_action_pairs(self):
        a = self.sample(); b = self.sample(5); b[1][1]['tick'] += 1
        report = compare.compare(a, b)
        self.assertEqual(dict(actionIndex=1, intervals=[6, 7], ticks=[[2, 8], [7, 14]],
                              methods=[['move', 'move'], ['move', 'move']]),
                         report['firstInterActionMismatch'])
        self.assertEqual([6, 7], report['actionSpanTicks'])
        self.assertIsNone(compare.compare(a, self.sample(5))['firstInterActionMismatch'])

    def test_missing_callback_is_a_cadence_mismatch_without_index_error(self):
        a = self.sample(); b = self.sample(); b[1].pop()
        self.assertEqual(dict(actionIndex=1, intervals=[6, None], ticks=[[2, 8], None],
                              methods=[['move', 'move'], None]),
                         compare.compare(a, b)['firstInterActionMismatch'])

    def test_failed_or_empty_runs_never_support_match(self):
        a = self.sample(); b = self.sample(); b[0]['status'] = 'failed'
        self.assertFalse(compare.compare(a, b)['bothPassed'])
        self.assertFalse(compare.compare(a, b)['selectedObservationsMatch'])
        a[1].clear(); b[1].clear()
        self.assertFalse(compare.compare(a, b)['callbackTuplesEqual'])

    def test_preparation_and_final_world_phase_are_not_hidden(self):
        a = self.sample(); b = self.sample()
        a[0].update(preparedStart=False, worldTotalTime=100, workerExecuting=False)
        b[0].update(preparedStart=True, worldTotalTime=101, workerExecuting=True)
        report = compare.compare(a, b)
        self.assertFalse(report['selectedObservationsMatch'])
        self.assertEqual([False, True], report['observationDifferences']['preparedStart'])
        self.assertEqual([100, 101], report['observationDifferences']['worldTotalTime'])
        self.assertEqual([False, True], report['observationDifferences']['workerExecuting'])

    def test_supervisor_failure_cannot_be_bypassed_by_retained_analysis(self):
        a = self.sample(); b = self.sample()
        b[2].update(status='failed', reason='wall timeout including cleanup')
        self.assertFalse(compare.compare(a, b)['bothPassed'])
        spec = importlib.util.spec_from_file_location('fidelity_analyze', Path(__file__).resolve().parent / 'fixtures/fidelity_analyze.py')
        analyzer = importlib.util.module_from_spec(spec); spec.loader.exec_module(analyzer)
        loaded = [(dict(result=result, supervisor=report), [], calls, None, [100, 99])
                  for result, calls, report in (a, b)]
        with patch.object(analyzer, 'load', side_effect=loaded):
            report = analyzer.analyze('reference', 'failed-process')
        self.assertFalse(report['bothPassed'])
        self.assertFalse(report['selectedObservationsMatch'])
        self.assertEqual('passed', b[0]['status'])  # Keep original mod evidence unchanged.

    def test_profiles_and_separate_wall_times_reported(self):
        a = self.sample(); b = self.sample(); b[2]['sha256']['template/mods/OpenComputers.jar'] = 'b'
        report = compare.compare(a, b)
        self.assertIn('template/mods/OpenComputers.jar', report['profileDifferences'])
        self.assertFalse(report['selectedObservationsMatch'])
        self.assertEqual([1, 1], report['totalWallSeconds'])


if __name__ == '__main__': unittest.main()
