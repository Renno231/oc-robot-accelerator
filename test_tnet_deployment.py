import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from lupa.lua53 import LuaRuntime

from examples.mes.build_fixtures import build_native


ROOT = Path(__file__).resolve().parent


class TnetDeploymentTests(unittest.TestCase):
    def test_installed_user_libraries_are_exact_frozen_bytes(self):
        manifest = json.loads((ROOT / 'craftsystem/tnet-provenance.json').read_text())
        for name, expected in manifest['libraries'].items():
            with self.subTest(library=name):
                data = (ROOT / 'craftsystem/usr/lib' / name).read_bytes()
                self.assertEqual(len(data), expected['bytes'])
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected['sha256'])
                source = Path(expected.get('source', str(Path(manifest['source']) / name)))
                if source.exists():
                    self.assertEqual(data, source.read_bytes().replace(b'\r\n', b'\n'))
        for expected in manifest.get('commands', {}).values():
            data = (ROOT / 'craftsystem' / expected['installed']).read_bytes()
            self.assertEqual(len(data), expected['bytes'])
            self.assertEqual(hashlib.sha256(data).hexdigest(), expected['sha256'])
            source = Path(expected['source'])
            if source.exists():
                self.assertEqual(data, source.read_bytes().replace(b'\r\n', b'\n'))

    def test_both_controller_and_robot_deploy_unchanged_libraries(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'fixture'
            build_native(target, 'torches16')
            for role in ('computer', 'robot'):
                for name in ('tnet.lua', 'api.lua', 'hosts.lua', 'pubsub.lua'):
                    paths = list(target.glob('**/usr/lib/' + name))
                    selected = [p for p in paths if ('robot-program' in p.parts) == (role == 'robot')]
                    self.assertTrue(selected, (role, name))
                    original = (ROOT / 'craftsystem/usr/lib' / name).read_bytes()
                    for path in selected:
                        self.assertEqual(path.read_bytes(), original)
            paths = [p for p in target.glob('**/usr/bin/pair.lua') if 'robot-program' not in p.parts]
            self.assertTrue(paths)
            for path in paths:
                self.assertEqual(path.read_bytes(), (ROOT / 'craftsystem/usr/bin/pair.lua').read_bytes())

    def test_native_observer_measures_packet_without_changing_send_arguments(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
            event={listen=function() end}
            computer={getDeviceInfo=function() return {modem={capacity='2048'}} end}
            serialization={serialize=function(value)
                if value.msg then ENCODED=value;return 'SERIALIZED' end
                return 'PLAN'
            end}
            net={connect=function() return {
                sys='craftClient',id='c1',msg_id=0,wake='wake',address='robot',port=5990,
                modem={address='modem',send=function() return true end},
                send=function(self,message,...)
                    SENT=table.pack(message,...)
                    local payload=serialization.serialize({msg=message,args=table.pack(...)})
                    self.modem.send(self.address,self.port,self.wake,'craftClient,c1,1,m',message,payload)
                    return 77,'original return'
                end
            } end}
            require=function(name)
                return ({event=event,computer=computer,serialization=serialization,tnet=net})[name]
            end
        ''')
        source = (ROOT / 'machine_evidence.lua').read_text()
        prefix = source.split("local starts=io.open", 1)[0]
        lua.execute('TRACE=(function()\n' + prefix + '\nreturn craftPayloads end)()')
        result = lua.execute('''
            local conn=require('tnet').connect('robot',5990)
            local first,second=conn:send('craft',{jobId='j1',plan={requestItem='t:x'}},nil,'extra')
            local row=TRACE[1]
            return first,second,SENT.n,SENT[4],ENCODED.args.n,ENCODED.args[3],
                row.payloadBytes,row.planBytes,row.packetBytes,row.packetLimit,#TRACE
        ''')
        self.assertEqual(result, (77, 'original return', 4, 'extra', 3, 'extra', 10, 4, 45, 2048, 1))
        rpc = lua.execute('''
            local conn=require('tnet').connect('robot',5990)
            conn:send('rpc','rpc_call','craft','call-1',table.pack({requestItem='t:y'},'j2',false),nil)
            local row=TRACE[2]
            return SENT.n,ENCODED.msg,ENCODED.args.n,row.jobId,row.planBytes,row.packetBytes,#TRACE
        ''')
        self.assertEqual(rpc, (6, 'rpc', 5, 'j2', 4, 43, 2))


if __name__ == '__main__':
    unittest.main()
