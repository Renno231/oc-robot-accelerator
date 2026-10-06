import copy
import json
from pathlib import Path
import tempfile
import unittest
import runner_scenario as scenario
from runner_jobs import _install
from runner_drones import completed_result


def valid():
    return json.loads(Path('examples/drones/link/scenario.json').read_text())


class ComputerScenarioTests(unittest.TestCase):
    def test_coordinated_computer_and_second_computer_keep_baseline_default(self):
        v=valid();self.assertEqual('baseline',scenario.normalize(v)['execution']['mode'])
        v['execution']={'mode':'coordinated'}
        v['secondComputer']=copy.deepcopy(v['computer']);v['secondComputer']['position']=[1,65,2]
        v['secondComputer']['program']['directory']='client'
        n=scenario.normalize(v);self.assertEqual('coordinated',n['execution']['mode'])
        self.assertEqual(n,scenario.normalize(n))

    def test_second_computer_shape_and_independent_freeze(self):
        v=valid();v['secondComputer']=copy.deepcopy(v['computer'])
        v['secondComputer']['position']=[1,65,2];v['secondComputer']['program']['directory']='client'
        n=scenario.normalize(v);self.assertEqual(n,scenario.normalize(n))
        self.assertEqual(n['secondComputer']['program']['directory'],'second-program')
        bad=copy.deepcopy(v);bad.pop('computer')
        with self.assertRaises(ValueError): scenario.normalize(bad)
        bad=copy.deepcopy(v);bad['secondComputer']['position']=bad['computer']['position']
        with self.assertRaises(ValueError): scenario.normalize(bad)
        for key,replacement in [('directory','../client'),('entry','../main.lua')]:
            bad=copy.deepcopy(v);bad['secondComputer']['program'][key]=replacement
            with self.assertRaises(ValueError): scenario.normalize(bad)
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);src=root/'src';src.mkdir()
            for name in ('program','client'):
                (src/name).mkdir();(src/name/'main.lua').write_text('print("'+name+'")')
            (src/'eeprom.lua').write_text('computer.shutdown()')
            (src/'scenario.json').write_text(json.dumps(v))
            spec=scenario.load(src/'scenario.json');scenario.freeze(spec,root/'inputs')
            run=root/'runtime';(run/'config/opencomputers').mkdir(parents=True)
            _install(root/'inputs',run,spec.normalized['execution'],lambda:None)
            self.assertEqual((run/'second-program/main.lua').read_text(),'print("client")')
            self.assertEqual((run/'program/main.lua').read_text(),'print("program")')
            v['secondComputer']['program']['directory']='program';(src/'scenario.json').write_text(json.dumps(v))
            with self.assertRaises(ValueError): scenario.load(src/'scenario.json')

    def test_second_completion_requires_return_and_no_native_error(self):
        v={'runnerSchemaVersion':1,'scenarioId':'test','mode':'baseline','drones':[],
           'computer':{'lastError':None},'program':{'status':'returned'},
           'secondComputer':{'lastError':None,'program':{'status':'returned'}}}
        completed_result(v,'test',0,True,True)
        for bad in ({}, {'lastError':'boom','program':{'status':'returned'}}, {'lastError':None,'program':{'status':'running'}}):
            v['secondComputer']=bad
            with self.assertRaises(ValueError): completed_result(v,'test',0,True,True)

    def test_shape_defaults_and_computer_only(self):
        v = valid(); n = scenario.normalize(v)
        self.assertEqual(n, scenario.normalize(n))
        self.assertEqual(n['computer']['program']['directory'], 'program')
        self.assertEqual(n['execution']['mode'], 'baseline')
        v.pop('drones'); v.pop('expect')
        n = scenario.normalize(v)
        self.assertEqual(n['drones'], [])
        self.assertEqual(n, scenario.normalize(n))
        v['drones'] = []; self.assertEqual(scenario.normalize(v)['drones'], [])

    def test_new_fields_reject_bad_shapes_and_bounds(self):
        cases = [(['computer'], []), (['computer', 'hardware', 'tier'], 'creative'),
                 (['computer', 'hardware', 'tier'], True), (['computer', 'hardware', 'tier'], 4),
                 (['computer', 'hardware', 'memory'], []), (['computer', 'hardware', 'storage'], []),
                 (['computer', 'hardware', 'bootDrive'], 1), (['computer', 'hardware', 'cards'], ['wlancard2'] * 4),
                 (['computer', 'hardware', 'upgrades'], []), (['computer', 'hardware', 'cpu'], '../cpu3'),
                 (['computer', 'position'], [99, 65, 0]), (['computer', 'program', 'entry'], '../main.lua'),
                 (['computer', 'program', 'entry'], 'main.txt'), (['computer', 'program', 'directory'], '/program'),
                 (['program'], {'directory': 'program'}), (['robot'], {}),
                 (['execution', 'mode'], 'paced'),
                 (['blocks'], valid()['blocks'] * 65), (['blocks'], valid()['blocks'] * 2),
                 (['blocks', 0, 'position'], [99, 65, 0]), (['blocks', 0, 'block'], 'not-registry'),
                 (['blocks', 0, 'properties'], {'bad key': 'foo'}), (['blocks', 0, 'properties'], {str(i): 'foo' for i in range(17)}),
                 (['expect', 'drones', 0, 'minEnergy'], True), (['expect', 'drones', 0, 'minEnergy'], -1),
                 (['expect', 'drones', 0, 'running'], 1)]
        cases += [(['blocks', 0, 'energy'], v) for v in (True, -1, float('inf'), float('nan'), 2147483648)]
        for path, replacement in cases:
            with self.subTest(path=path, value=str(replacement)[:80]):
                v = valid(); target = v
                for key in path[:-1]: target = target[key]
                target[path[-1]] = replacement
                with self.assertRaises(ValueError): scenario.normalize(v)
        for field in ('position', 'hardware', 'program'):
            v = valid(); del v['computer'][field]
            with self.assertRaises(ValueError): scenario.normalize(v)

    def test_program_and_eeprom_freeze_install(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); src = root / 'src'; src.mkdir(); (src / 'program').mkdir()
            (src / 'program/main.lua').write_text('print("controller")')
            (src / 'eeprom.lua').write_text('computer.shutdown()')
            v = valid(); (src / 'scenario.json').write_text(json.dumps(v))
            spec = scenario.load(src / 'scenario.json'); scenario.freeze(spec, root / 'inputs')
            run = root / 'runtime'; (run / 'config/opencomputers').mkdir(parents=True)
            _install(root / 'inputs', run, spec.normalized['execution'], lambda: None)
            self.assertEqual((run / 'program/main.lua').read_text(), 'print("controller")')
            self.assertEqual((run / 'eeprom/eeprom.lua').read_text(), 'computer.shutdown()')
            (src / 'program/main.lua').unlink()
            with self.assertRaises(ValueError): scenario.load(src / 'scenario.json')

    def test_controller_completion_allows_live_drone_but_not_error(self):
        value = {'runnerSchemaVersion': 1, 'scenarioId': 'test', 'mode': 'baseline',
                 'computer': {'lastError': None}, 'program': {'status': 'returned'},
                 'drones': [{'index': 0, 'state': 'Sleeping', 'lastError': None}]}
        completed_result(value, 'test', 1, True)
        with self.assertRaises(ValueError): completed_result(value, 'test', 1)
        for path in ('computer', 'drones'):
            v = copy.deepcopy(value)
            (v[path][0] if path == 'drones' else v[path])['lastError'] = 'boom'
            with self.assertRaises(ValueError): completed_result(v, 'test', 1, True)
        value['program']['status'] = 'error'
        with self.assertRaises(ValueError): completed_result(value, 'test', 1, True)


if __name__ == '__main__': unittest.main()
