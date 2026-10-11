"""Evidence decoder checked against the production Lua encoder, not a copy."""
from pathlib import Path
import tempfile
import unittest
from lupa.lua53 import LuaRuntime
from native_store_evidence import enrich, read_store, value


class NativeStoreEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(encoding=None)
        self.lua.execute(b'cbor=assert(load(...))()', Path('drone-logistics/lib/cbor.lua').read_bytes())

    def encode(self, expression):
        return self.lua.eval(('cbor.encode(' + expression + ')').encode('utf-8'))

    def test_production_numbers_strings_arrays_maps_and_empty_tables(self):
        data = self.encode('{name="café",n=-500,large=4294967297,small=0.5,yes=true,no=false,empty={},list={1,2}}')
        self.assertEqual(value(data), {'name': 'café', 'n': -500, 'large': 4294967297,
                                      'small': 0.5, 'yes': True, 'no': False,
                                      'empty': [], 'list': [1, 2]})

    def test_log_replacements_deletions_and_staging_are_store_format(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'warehouse.db'
            path.write_bytes(self.encode('{k="stock",v={count=5}}') +
                             self.encode('{k="removed",v=false}') +
                             self.encode('{k="stock",v={count=3}}') +
                             self.encode('{k="removed"}'))
            Path(str(path) + '.new').write_bytes(b'not the committed store')
            self.assertEqual(read_store(path), {'stock': {'count': 3}})

    def test_files_store_percent_escaped_key_and_false_value(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'key%2Fwith%25space%20%C3%A9').write_bytes(self.encode('false'))
            self.assertEqual(read_store(path), {'key/with%space é': False})

    def test_decoder_reports_log_byte_offset_and_rejects_trailing_value(self):
        data = self.encode('{k="good",v=1}')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'warehouse.db'
            path.write_bytes(data + b'\xa1')
            with self.assertRaisesRegex(ValueError, 'at byte ' + str(len(data))):
                read_store(path)
        with self.assertRaisesRegex(ValueError, 'trailing bytes'):
            value(self.encode('1') + self.encode('2'))

    def test_all_five_real_native_stores_enrich_observer(self):
        with tempfile.TemporaryDirectory() as directory:
            drive = Path(directory); (drive / 'etc').mkdir()
            for name in ('map.db', 'warehouse.db', 'warehouse.flight', 'logistics.state', 'mes.state'):
                (drive / 'etc' / name).write_bytes(self.encode('{k="record",v={done=true}}'))
            evidence = enrich({'files': []}, drive)
            self.assertEqual(len(evidence['files']), 5)
            self.assertTrue(evidence['files']['/etc/map.db']['record']['done'])
            self.assertTrue(evidence['files']['/etc/mes.state']['record']['done'])


if __name__ == '__main__':
    unittest.main()
