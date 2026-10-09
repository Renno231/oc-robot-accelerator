import unittest
from unittest.mock import patch
from pathlib import Path

from lupa.lua53 import LuaRuntime

from run_mes_scenarios import acceptance_error, summarize_job


class MesAcceptanceGateTests(unittest.TestCase):
    def test_unavailable_job_without_elapsed_time_is_not_accepted(self):
        with patch('run_mes_scenarios.read_job', return_value=(None, None, None)):
            row = summarize_job({'jobId': 'pending', 'state': 'unavailable'}, 1,
                                Path('jobs'), Path('fixtures/torches16'), 'torches16', 'coordinated')
        self.assertIsNone(row['wallSeconds'])
        self.assertFalse(row['accepted'])
        self.assertEqual('native scenario failed', row['acceptanceError'])

    def row(self, **changes):
        row = {'case': 'torches16', 'mode': 'coordinated', 'state': 'passed',
               'commandExit': 0, 'droneTrips': 152, 'mesTrips': 21, 'harnessTrips': 131,
               'submitterExit': {'returned': True, 'statusAtReturn': 'running'},
               'componentCalls': {'scope': 'controller', 'total': 42},
               'robotIntervals': [{}, {}, {}, {}], 'robotOverlap': True}
        row.update(changes)
        return row

    def test_torch_mes_trips_strictly_improve_same_split_t11(self):
        self.assertIsNone(acceptance_error(self.row()))
        for trips in (24, 25, None, True, -1):
            with self.subTest(trips=trips):
                self.assertIsNotNone(acceptance_error(self.row(mesTrips=trips)))

    def test_missing_evidence_is_not_silent_success(self):
        row = self.row()
        del row['mesTrips']
        self.assertIsNotNone(acceptance_error(row))

    def test_baseline_is_measured_without_claiming_graph_improvement(self):
        self.assertIsNone(acceptance_error(self.row(mode='baseline', droneTrips=155, mesTrips=24)))

    def test_harness_reduction_cannot_hide_a_nonimproving_mes(self):
        self.assertIsNotNone(acceptance_error(self.row(droneTrips=100, mesTrips=24)))
        self.assertIsNone(acceptance_error(self.row(droneTrips=160, mesTrips=21)))

    def test_native_failure_is_not_accepted_even_with_fewer_trips(self):
        self.assertIsNotNone(acceptance_error(self.row(state='failed')))
        self.assertIsNotNone(acceptance_error(self.row(commandExit=1)))

    def test_oc_requires_native_payload_measurement_with_observed_packet_limit(self):
        row = self.row(case='ocparts', craftPayloads=[{'packetBytes': 2048, 'packetLimit': 8192}])
        self.assertIsNone(acceptance_error(row))
        for payloads in (None, [], [{'packetBytes': 8193, 'packetLimit': 8192}],
                         [{'packetBytes': 100, 'packetLimit': None}]):
            with self.subTest(payloads=payloads):
                self.assertIsNotNone(acceptance_error(self.row(case='ocparts', craftPayloads=payloads)))

    def test_oc_requires_service_lifetime_overlap_and_component_evidence(self):
        for changes in ({'submitterExit': None}, {'submitterExit': {'returned': True, 'statusAtReturn': 'complete'}},
                        {'componentCalls': None}, {'componentCalls': {'scope': 'controller', 'total': 0}},
                        {'robotIntervals': [{}, {}, {}]}, {'robotOverlap': None}):
            with self.subTest(changes=changes):
                self.assertIsNotNone(acceptance_error(self.row(case='ocparts',
                    craftPayloads=[{'packetBytes': 2048, 'packetLimit': 8192}], **changes)))
        self.assertIsNone(acceptance_error(self.row(case='ocparts', robotOverlap=False,
            craftPayloads=[{'packetBytes': 2048, 'packetLimit': 8192}])))

    def test_fixture_drains_last_observer_before_actual_job_trip_split(self):
        source = Path('examples/mes/main.lua').read_text()
        helper = source.split('local function latestJobId()')[1].split('local address,distances')[0]
        lua = LuaRuntime()
        lua.execute('''
          local lg={jobs=function() return {{id=6}} end,drones=function() return {{name='d1'},{name='d2'}} end}
          local jobs={[1]={trips=2},[2]={trips=1},[3]={trips=2},[4]={trips=1},[5]={trips=3}}
          local totals={trips=9}
          jobs[2].tripTimings={{drone='d1',startedAt=10,finishedAt=13}}
          jobs[5].tripTimings={{drone='d2',startedAt=20,finishedAt=25}}
          local waited=false
          local function wait(fn)
            assert(not fn());waited=true
            jobs[6]={trips=1};totals.trips=10;assert(fn())
          end
        ''' + 'local function latestJobId()' + helper + '''
          local result={mesTripWindow={first=2,last=4}}
          finishTripAccounting(result)
          assert(waited and result.trips==10 and result.mesTrips==4 and result.harnessTrips==6)
          assert(result.droneBusy.d1.seconds==3 and result.droneBusy.d1.mesSeconds==3 and result.droneBusy.d1.mesTrips==1)
          assert(result.droneBusy.d2.seconds==5 and result.droneBusy.d2.mesSeconds==0 and result.droneBusy.d2.mesTrips==0)
        ''')
