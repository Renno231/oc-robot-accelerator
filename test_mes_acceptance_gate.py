"""The active matrix stages canonical sources and fails closed on evidence gaps."""
import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.mes.build_fixtures import (ALL_CASES, OCPARTS_FINAL, OCPARTS_REPEAT_FINAL,
                                        ROBOT_PARTS, ROBOT_PARTS_FINAL, ROBOT_EXPAND_FINAL, ROOT, build_native, split_item)
from run_mes_scenarios import trip_report, verify_case
import runner_scenario


class MesAcceptanceGateTests(unittest.TestCase):
    def test_io_sensors_have_a_floor_for_native_block_placement(self):
        from build_native_io_flow import build
        with tempfile.TemporaryDirectory() as temporary:
            value=json.loads(build(Path(temporary)).read_text())
            for sensor in value['microcontrollers']:
                x,y,z=sensor['position'];point=(x,y-1,z)
                block=None
                for region in value['world']['blocks']:
                    if all(a<=p<=b for a,p,b in zip(region['min'],point,region['max'])):
                        block=region['block']
                self.assertEqual(block,'minecraft:stone')

    def ocparts_evidence(self):
        stacks=[]
        for identity, count in OCPARTS_FINAL.items():
            if count:
                name, damage=split_item(identity)
                stacks.append({'item':name, 'metadata':damage, 'count':count})
        native={'status':'passed', 'drones':[{'inventory':[]} for _ in range(6)],
                'robots':[{'inventoryCapacity':85, 'inventory':[]} for _ in range(2)],
                'containers':[{'slots':stacks}]}
        stages=[{'kind':'robot', 'crafter':'cpu'+str(i%2+1), 'craftStarted':i*2,
                 'craftFinished':i*2+1} for i in range(4)]
        stages.append({'kind':'machine', 'state':'done', 'loadLedger':[
            {'group':group, 'items':16, 'delivered':start, 'collected':10}
            for group in ('furnaceA','furnaceB') for start in (1,2)]})
        return native, {'done_1':{'status':'complete', 'stages':stages}}

    def verify_ocparts(self, native, store, case='ocparts'):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'result.json').write_text(json.dumps(native))
            ledger=root/'world/opencomputers/controller/etc/mes.history'
            ledger.parent.mkdir(parents=True);ledger.touch()
            with patch('run_mes_scenarios.read_store', return_value=store):
                return verify_case(case, root)

    def test_successive_ocparts_gate_checks_surplus_and_stock(self):
        native, _ = self.ocparts_evidence()
        native['containers'][0]['slots'] = [dict(item=split_item(k)[0], metadata=split_item(k)[1], count=v)
                                           for k, v in OCPARTS_REPEAT_FINAL.items()]
        later = [{'kind': 'robot', 'outputs': [{'item': 'minecraft:iron_nugget'}, {'item': 'opencomputers:component:6'}]},
                 {'kind': 'machine', 'outputs': [{'item': 'opencomputers:material:4'}],
                  'loadLedger': [{'items': 3, 'inputs': [{'role': 'input', 'wanted': 3}]}]}]
        first = {'id': 1, 'qty': 5, 'status': 'complete', 'finished': 10, 'stages': []}
        second = {'id': 2, 'qty': 3, 'status': 'complete', 'started': 11, 'stages': later}
        store = {'done_1': first, 'done_2': second}
        self.verify_ocparts(native, store, 'ocparts-repeat')
        for fault in ('reset stock', 'overlap', 'remade chips'):
            with self.subTest(fault=fault):
                bad_native, bad_store = copy.deepcopy((native, store))
                if fault == 'reset stock': bad_native['containers'][0]['slots'][0]['count'] += 1
                elif fault == 'overlap': bad_store['done_2']['started'] = 9
                else: bad_store['done_2']['stages'][0]['outputs'].append({'item': 'opencomputers:material:7'})
                with self.assertRaises(AssertionError):
                    self.verify_ocparts(bad_native, bad_store, 'ocparts-repeat')

    def test_active_ocparts_gate_accepts_conserved_stock_and_real_load_topups(self):
        self.verify_ocparts(*self.ocparts_evidence())

    def test_robot_parts_gate_requires_every_order_and_conserved_stock(self):
        native, _ = self.ocparts_evidence()
        native['containers'][0]['slots'] = [dict(item=split_item(k)[0], metadata=split_item(k)[1], count=v)
                                           for k, v in ROBOT_PARTS_FINAL.items()]
        store = {'done_'+str(i): dict(id=i, item=k, qty=v, status='complete', stages=[],
                                     started=i*2, finished=i*2+1)
                 for i, (k, v) in enumerate(ROBOT_PARTS.items(), 1)}
        self.verify_ocparts(native, store, 'robot-parts')
        for fault in ('missing part', 'extra stock', 'missing receipt', 'wrong order', 'overlap'):
            with self.subTest(fault=fault):
                bad_native, bad_store = copy.deepcopy((native, store))
                stacks = bad_native['containers'][0]['slots']
                if fault == 'missing part': stacks.pop(0)
                elif fault == 'extra stock': stacks[-1]['count'] += 1
                elif fault == 'missing receipt': bad_store.pop('done_1')
                elif fault == 'wrong order': bad_store['done_1']['qty'] = 2
                else: bad_store['done_2']['started'] = 0
                with self.assertRaises(AssertionError): self.verify_ocparts(bad_native, bad_store, 'robot-parts')

    def test_expansion_gate_requires_new_robot_work_and_conserved_parts(self):
        native, _ = self.ocparts_evidence()
        native['robots'].append({'inventoryCapacity': 85, 'inventory': []})
        native['containers'][0]['slots'] = [dict(item=split_item(k)[0], metadata=split_item(k)[1], count=v)
                                           for k, v in ROBOT_EXPAND_FINAL.items()]
        native['containers'] += [dict(position=p, slots=[]) for p in ([11, 65, 3], [12, 65, 1])]
        native['containers'][0]['position'] = [0, 65, 0]
        store = {'done_'+str(i): dict(id=i, item=k, qty=v, status='complete', stages=[],
                                     started=i*2, finished=i*2+1)
                 for i, (k, v) in enumerate(ROBOT_PARTS.items(), 1)}
        for i, (item, qty, cpu) in enumerate([('opencomputers:component:11', 2, 'cpu3'),
                                             ('minecraft:chest', 1, 'cpu1'), ('minecraft:chest', 1, 'cpu2')], 14):
            store['done_'+str(i)] = dict(id=i, item=item, qty=qty, status='complete', started=30, finished=40,
                                        stages=[dict(kind='robot', crafter=cpu, craftStarted=31, craftFinished=39)])
        self.verify_ocparts(native, store, 'robot-expand')
        for fault in ('missing robot', 'wrong capacity', 'old robot', 'serial work', 'unused parts', 'missing output'):
            with self.subTest(fault=fault):
                bad_native, bad_store = copy.deepcopy((native, store))
                if fault == 'missing robot': bad_native['robots'].pop()
                elif fault == 'wrong capacity': bad_native['robots'][2]['inventoryCapacity'] = 16
                elif fault == 'old robot': bad_store['done_14']['stages'][0]['crafter'] = 'cpu1'
                elif fault == 'serial work': bad_store['done_16']['started'] = 41
                elif fault == 'unused parts': bad_native['containers'][1]['slots'] = [dict(item='opencomputers:case3', count=1)]
                else: bad_native['containers'][0]['slots'][0]['count'] -= 1
                with self.assertRaises(AssertionError): self.verify_ocparts(bad_native, bad_store, 'robot-expand')

    def test_active_ocparts_gate_rejects_missing_or_contradictory_evidence(self):
        for fault in ('extra stock', 'missing stock', 'missing machine', 'missing load',
                      'wrong split', 'late topup', 'robot overlap'):
            with self.subTest(fault=fault):
                native, store=self.ocparts_evidence()
                stages=store['done_1']['stages'];loads=stages[-1]['loadLedger']
                if fault=='extra stock': native['containers'][0]['slots'].append({'item':'minecraft:diamond','count':1})
                elif fault=='missing stock': native['containers'][0]['slots'].pop()
                elif fault=='missing machine': stages.pop()
                elif fault=='missing load': loads.pop()
                elif fault=='wrong split': loads[0]['group']='furnaceB'
                elif fault=='late topup': loads[1]['delivered']=loads[0]['collected']
                elif fault=='robot overlap': stages[2]['craftStarted']=0
                with self.assertRaises(AssertionError): self.verify_ocparts(native, store)

    def test_every_case_stages_current_source_real_pairing_and_full_hardware(self):
        with tempfile.TemporaryDirectory() as temporary:
            for case in ALL_CASES:
                with self.subTest(case=case):
                    path = build_native(Path(temporary) / case, case)
                    runner_scenario.load(path)
                    value = json.loads(path.read_text())
                    hardware = value['controller']['hardware']
                    self.assertEqual(['ram6'] * 4, hardware['memory'])
                    self.assertEqual(6, len(value['drones']))
                    program = path.parent / 'program'
                    for source in (ROOT/'drone-logistics/lib').glob('*.lua'):
                        self.assertEqual(source.read_bytes(), (program/'usr/lib'/source.name).read_bytes())
                    for source in (ROOT/'craftsystem/usr').rglob('*'):
                        if source.is_file() and '/mes/ui/' not in source.as_posix() and source.name != 'mesui.lua':
                            self.assertEqual(source.read_bytes(), (program/'usr'/source.relative_to(ROOT/'craftsystem/usr')).read_bytes())
                    main = (program/'main.lua').read_text()
                    self.assertIn('mes.registerRobot(', main)
                    self.assertIn("rc('mes','start')", main)
                    self.assertNotIn('mes_robot_query', main)
                    self.assertNotIn('addHost', main)
                    self.assertFalse((program/'component-counter.lua').exists())
                    for index, robot in enumerate(value['robots'], 1):
                        setup = (program/'setup.lua').read_text()
                        if 'assembly' in robot:
                            self.assertNotIn('cpu'+str(index)+'.buf', setup)
                            self.assertIn('cpu'+str(index)+'.buf', main)
                        else: self.assertIn('cpu'+str(index)+'.buf', setup)
                        self.assertEqual(['ram6', 'ram6'], robot['hardware']['memory'])
                        self.assertEqual(3, len(robot['hardware']['containers']))
                        self.assertEqual(3, robot['hardware']['upgrades'].count('inventoryupgrade'))
                        disk = path.parent / robot['program']['directory']
                        for installed in (disk/'usr').rglob('*'):
                            if installed.is_file():
                                source = ROOT/'craftsystem/usr'/installed.relative_to(disk/'usr')
                                self.assertEqual(source.read_bytes(), installed.read_bytes())
                        self.assertEqual((ROOT/'craftsystem/usr/bin/cproc.lua').read_bytes(),
                                         (disk/'usr/bin/cproc.lua').read_bytes())
                        self.assertIn("rc('cproc','start')", (disk/'main.lua').read_text())
                        self.assertNotIn('addHost', (disk/'main.lua').read_text())
                    self.assertEqual(85, len(value['expect']['robots'][0]['inventory']))
                    with self.assertRaises(FileExistsError):
                        build_native(path.parent, case)

    def test_deferred_assembly_requires_bounded_source_and_trigger(self):
        with tempfile.TemporaryDirectory() as temporary:
            value = json.loads(build_native(Path(temporary) / 'fixture', 'robot-expand').read_text())
            normalized = runner_scenario.normalize(value)
            self.assertEqual([11, 65, 3], normalized['robots'][2]['assembly']['source'])
            for fault in ('source', 'marker', 'controller', 'block', 'energy', 'unknown', 'first robot'):
                with self.subTest(fault=fault):
                    bad = copy.deepcopy(value); assembly = bad['robots'][2]['assembly']
                    if fault == 'source': assembly['source'] = [1, 65, 0]
                    elif fault == 'marker': assembly['request']['marker'] = '../outside'
                    elif fault == 'controller': assembly['request']['computer'] = 1
                    elif fault == 'block': assembly['blocks'][0]['position'] = [99, 65, 0]
                    elif fault == 'energy': assembly['blocks'][0]['energy'] = 100
                    elif fault == 'unknown': assembly['ignoreMissing'] = True
                    else: bad['robots'][0]['assembly'] = bad['robots'][2].pop('assembly')
                    with self.assertRaises(ValueError): runner_scenario.normalize(bad)

    def capture(self, root, *, summary=True, dispatch=True, receipt=True, report_token='token'):
        frames=[]
        def frame(parts):
            frames.append({'kind': 'modemFrame', 'sequence': len(frames)+1, 'tick': 1,
                           'source': 'modem', 'destination': 'modem', 'direction': 'send', 'port': 27103, 'parts': parts})
        if dispatch:
            frame(['token', 'trip', 1, {'base64': base64.b64encode(b'{steps={}}').decode()}])
        frame([report_token, 'report', 1, '{state="idle"}'])
        if summary:
            frames.append({'kind': 'captureSummary', 'streamComplete': True,
                           'decodeCoverageComplete': True, 'frameObservations': len(frames)})
        path=root/'capture.ndjson'
        path.write_text(''.join(json.dumps(row)+'\n' for row in frames))
        ledger=root/'world/opencomputers/controller/etc/logistics.state'
        ledger.parent.mkdir(parents=True);ledger.touch()
        jobs={'job_1': {'id': 1, 'state': 'done', 'tripTimings': {1: {'trip': 1, 'finishedAt': 2}}}} if receipt else {}
        with patch('run_mes_scenarios.read_store', return_value=jobs):
            return trip_report(path, root)

    def test_complete_capture_joins_dispatch_to_persisted_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            report=self.capture(Path(temporary))
            self.assertTrue(report['coverageComplete'])
            self.assertEqual({'steps': {}}, report['trips']['1']['dispatches'][0]['data'])
            self.assertIn('Human trip walk required', report['review'])

    def test_missing_capture_or_dispatch_cannot_be_called_complete(self):
        for missing in ('summary', 'dispatch'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temporary:
                report=self.capture(Path(temporary), **{missing: False})
                self.assertFalse(report['coverageComplete'])

    def test_completed_jobs_can_age_out_of_the_live_32_job_ledger(self):
        with tempfile.TemporaryDirectory() as temporary:
            report=self.capture(Path(temporary), receipt=False)
            self.assertTrue(report['coverageComplete'])

    def test_wrong_token_report_is_not_completion_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertFalse(self.capture(Path(temporary), report_token='wrong')['coverageComplete'])


if __name__ == '__main__':
    unittest.main()
