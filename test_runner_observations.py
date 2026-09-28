"""Recorded playback is reconstruction of samples, not deterministic resimulation."""
import json
from pathlib import Path
import tempfile
import unittest
import runner_observations as obs


def records():
    robot = {'position':[0,65,0], 'facing':'north', 'energy':100, 'state':'Stopped', 'inventory':[], 'tool':{}}
    first = {'schemaVersion':1,'sequence':0,'tick':1,'kind':'initial','region':{'min':[0,65,0],'max':[0,65,1]},
             'everyTicks':20,'robot':robot,'blocks':[{'position':[0,65,z],'block':'minecraft:air','properties':{}} for z in (0,1)]}
    last = {'schemaVersion':1,'sequence':1,'tick':20,'kind':'final','robot':dict(robot,energy=95),
            'blocks':[{'position':[0,65,1],'block':'minecraft:stone','properties':{}}]}
    return [first,last]


class Observations(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'observations.ndjson'

    def store(self, items):
        self.path.write_text(''.join(json.dumps(r)+'\n' for r in items),encoding='utf-8')

    def test_reconstruct_initial_plus_deltas(self):
        self.store(records()); state=obs.reconstruct(self.path)
        self.assertEqual(state['blocks'][(0,65,1)]['block'],'minecraft:stone')
        self.assertEqual(state['last']['robot']['energy'],95)
        self.assertTrue(state['summary']['finalRecorded'])
        self.assertEqual(state['summary']['records'],2)
        self.assertEqual(state['summary']['everyTicks'],20)
        self.assertNotIn('blocks',state['summary'])

    def test_partial_live_line_is_explicit_and_not_applied(self):
        self.store(records()[:1])
        with self.path.open('ab') as out: out.write(b'{"sequence":1')
        state=obs.reconstruct(self.path)
        self.assertTrue(state['summary']['truncatedLastLine'])
        self.assertFalse(state['summary']['finalRecorded'])
        self.assertEqual(state['summary']['records'],1)
        self.assertEqual(state['blocks'][(0,65,1)]['block'],'minecraft:air')

    def test_missing_and_empty_are_unavailable_not_success(self):
        self.assertFalse(obs.summary(self.path)['available'])
        self.path.touch(); self.assertFalse(obs.summary(self.path)['available'])

    def test_malformed_order_and_incomplete_initial_fail(self):
        for mutation in ['sequence','backwards','missing-cell','outside','after-final','duplicate-key']:
            rows=records()
            if mutation=='sequence': rows[1]['sequence']=3
            elif mutation=='backwards': rows[1]['tick']=0
            elif mutation=='missing-cell': rows[0]['blocks'].pop()
            elif mutation=='outside': rows[1]['blocks'][0]['position']=[1,65,1]
            elif mutation=='after-final': rows.append(dict(rows[1],sequence=2))
            self.store(rows)
            if mutation=='duplicate-key': self.path.write_text('{"schemaVersion":1,"schemaVersion":1}\n')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): obs.reconstruct(self.path)

    def test_byte_and_line_bounds(self):
        self.store(records())
        with self.assertRaises(ValueError): obs.reconstruct(self.path,max_bytes=5)
        with self.assertRaises(ValueError): obs.reconstruct(self.path,max_line=5)


if __name__=='__main__': unittest.main()
