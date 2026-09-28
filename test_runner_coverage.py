"""Retained NDJSON is authoritative; sidecars are bounded, fallible checkpoints."""
import json
from pathlib import Path
import tempfile
import unittest

import runner_observations as observations
from test_runner_observations import records


class Coverage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'observations.ndjson'
        self.status = self.path.with_name('observations-status.json')
        self.rows = records()
        self.lines = [(json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8') for row in self.rows]

    def checkpoint(self, count=2, **changes):
        value = {'schemaVersion':1, 'policy':'stop', 'maxBytes':33554432,
                 'bytesWritten':sum(map(len,self.lines[:count])), 'recordsWritten':count,
                 'lastRecordedTick':self.rows[count-1]['tick'] if count else None,
                 'lastObservedTick':self.rows[count-1]['tick'] if count else None,
                 'recordingStopped':False, 'stopReason':None,
                 'finalRecorded':bool(count and self.rows[count-1]['kind']=='final')}
        value.update(changes)
        self.status.write_text(json.dumps(value), encoding='utf-8')
        return value

    def stream(self, count=2, tail=b''):
        self.path.write_bytes(b''.join(self.lines[:count])+tail)

    def test_historical_missing_status_preserves_summary(self):
        self.stream(); value=observations.summary(self.path)
        self.assertEqual(value['coverageStatus'],'missing')
        self.assertIsNone(value['observationCoverage'])
        self.assertIsInstance(value['coverage'],str)
        self.assertEqual(value['bytesRecorded'],sum(map(len,self.lines)))
        self.assertEqual(value['records'],2)
        self.assertTrue(value['finalRecorded'])

    def test_matching_closed_and_stopped_prefix_checkpoints(self):
        self.stream(); checkpoint=self.checkpoint()
        value=observations.summary(self.path)
        self.assertEqual(value['coverageStatus'],'consistent')
        self.assertEqual(value['observationCoverage'],checkpoint)
        self.stream(1); checkpoint=self.checkpoint(1,recordingStopped=True,
                                                 stopReason='byte_limit',lastObservedTick=90000)
        state=observations.reconstruct(self.path)
        self.assertEqual(state['summary']['coverageStatus'],'consistent')
        self.assertEqual(state['summary']['lastTick'],1)
        self.assertFalse(state['summary']['finalRecorded'])
        self.assertEqual(state['last']['tick'],1)  # Never extrapolate through omitted time.
        self.assertEqual(state['blocks'][(0,65,1)]['block'],'minecraft:air')
        self.assertEqual(state['summary']['observationCoverage'],checkpoint)

    def test_behind_checkpoint_must_match_actual_prefix_not_just_small_counters(self):
        self.stream()
        for count in (0,1):
            with self.subTest(count=count):
                self.checkpoint(count)
                self.assertEqual(observations.summary(self.path)['coverageStatus'],'stale')
        for changes in ({'bytesWritten':1},{'lastRecordedTick':0,'lastObservedTick':0},
                        {'finalRecorded':True}, {'recordingStopped':True,'stopReason':'byte_limit'}):
            with self.subTest(changes=changes):
                self.checkpoint(1,**changes)
                self.assertEqual(observations.summary(self.path)['coverageStatus'],'ahead')

    def test_ahead_or_contradictory_sidecar_cannot_extend_stream(self):
        self.stream(1,tail=b'{"sequence":1')
        self.checkpoint()
        value=observations.summary(self.path)
        self.assertEqual(value['coverageStatus'],'ahead')
        self.assertEqual(value['records'],1)
        self.assertTrue(value['truncatedLastLine'])
        self.assertFalse(value['finalRecorded'])
        self.assertEqual(value['bytesRecorded'],len(self.lines[0]))
        self.assertGreater(value['bytesRead'],value['bytesRecorded'])
        self.stream(); self.checkpoint(bytesWritten=sum(map(len,self.lines))-1)
        self.assertEqual(observations.summary(self.path)['coverageStatus'],'ahead')

    def test_invalid_status_does_not_discard_valid_recording(self):
        self.stream()
        invalid = [dict(recordsWritten=True),dict(bytesWritten=-1),dict(maxBytes=33554433),dict(maxBytes=1048575),
                   dict(lastObservedTick=0),dict(recordingStopped=True),dict(stopReason='byte_limit'),
                   dict(policy='unknown'),dict(schemaVersion=2),dict(finalRecorded=1),
                   dict(recordsWritten=0,bytesWritten=1,lastRecordedTick=None,finalRecorded=False)]
        for changes in invalid:
            with self.subTest(changes=changes):
                self.checkpoint(**changes)
                value=observations.summary(self.path)
                self.assertEqual(value['coverageStatus'],'invalid')
                self.assertIsNone(value['observationCoverage'])
                self.assertEqual(value['records'],2)
        for raw in (b'{', b'x'*65537, b'{"schemaVersion":1,"schemaVersion":1}', b'{"bytesWritten":1e999}'):
            with self.subTest(raw=raw[:60]):
                self.status.write_bytes(raw)
                self.assertEqual(observations.summary(self.path)['coverageStatus'],'invalid')

    def test_recorded_stream_beyond_checkpoint_cap_is_contradictory(self):
        self.rows[1]['blocks'][0]['properties']={'label':'x'*1048576}
        self.lines=[(json.dumps(row)+'\n').encode() for row in self.rows]
        self.stream(); self.checkpoint(1,maxBytes=1048576)
        value=observations.summary(self.path)
        self.assertEqual(value['coverageStatus'],'ahead')
        self.assertEqual(value['records'],2)

    def test_missing_stream_and_initial_checkpoint_are_distinct(self):
        self.checkpoint(0)
        value=observations.summary(self.path)
        self.assertFalse(value['available']); self.assertEqual(value['coverageStatus'],'consistent')
        self.checkpoint()
        self.assertEqual(observations.summary(self.path)['coverageStatus'],'ahead')

    def test_publication_temp_cap_is_checked_without_reading_partial_data(self):
        self.stream(); self.checkpoint()
        temporary=self.path.with_name('.observations-status.json.tmp')
        temporary.write_bytes(b'{')
        self.assertEqual(observations.summary(self.path)['coverageStatus'],'consistent')
        temporary.write_bytes(b'x'*65537)
        self.assertEqual(observations.summary(self.path)['coverageStatus'],'invalid')
        self.assertEqual(observations.summary(self.path)['records'],2)

    def test_bytes_are_utf8_and_ticks_nonnegative(self):
        self.rows[0]['blocks'][0]['properties']={'label':'é'}
        self.lines=[(json.dumps(row,ensure_ascii=False)+'\n').encode('utf-8') for row in self.rows]
        self.stream(); self.checkpoint()
        self.assertEqual(observations.summary(self.path)['coverageStatus'],'consistent')
        self.rows[0]['tick']=-1
        self.path.write_bytes((json.dumps(self.rows[0])+'\n').encode())
        with self.assertRaisesRegex(ValueError,'tick'): observations.summary(self.path)


if __name__=='__main__': unittest.main()
