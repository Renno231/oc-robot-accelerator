"""A Windows metadata sharing collision must not detach a healthy foreground job."""
from unittest import mock
import unittest
import runner_jobs as jobs


class StatusSharingTests(unittest.TestCase):
    def test_short_sharing_collision_retries_without_inventing_state(self):
        identity='a'*32
        valid=dict(schemaVersion=1,jobId=identity,state='running',heartbeat=100,created=90,
                   acknowledged=True,scenarioId='test',reason='server running')
        with mock.patch.object(jobs,'_job',return_value=jobs.Path('job')), \
                mock.patch.object(jobs.scenario,'read_json',side_effect=[PermissionError('sharing'),valid]) as read, \
                mock.patch.object(jobs.time,'time',return_value=100), mock.patch.object(jobs.time,'sleep') as sleep:
            self.assertEqual(jobs.status('root',identity)['state'],'running')
            self.assertEqual(read.call_count,2); sleep.assert_called_once_with(.025)

    def test_persistent_sharing_collision_remains_unavailable_boundedly(self):
        with mock.patch.object(jobs,'_job',return_value=jobs.Path('job')), \
                mock.patch.object(jobs.scenario,'read_json',side_effect=PermissionError('sharing')) as read, \
                mock.patch.object(jobs.time,'sleep'):
            self.assertEqual(jobs.status('root','a'*32)['state'],'unavailable')
            self.assertEqual(read.call_count,3)


if __name__=='__main__': unittest.main()
