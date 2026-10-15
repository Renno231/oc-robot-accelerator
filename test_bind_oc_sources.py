from pathlib import Path
import tempfile
import unittest

from bind_oc_sources import bind


class SourceBindings(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'accelerator'
        self.sources = Path(temp.name) / 'OC-Utilities'
        self.root.mkdir()
        for name in ('craftsystemv4_mes', 'drone-logistics'):
            (self.sources / name).mkdir(parents=True)

    def test_binds_actual_sources_and_is_repeatable(self):
        bind(self.root, self.sources)
        bind(self.root, self.sources)
        for local, canonical in [('craftsystem', 'craftsystemv4_mes'), ('drone-logistics', 'drone-logistics')]:
            path = self.root / local
            self.assertEqual(path.resolve(), self.sources / canonical)
            (path / 'probe').write_text('same file')
            self.assertEqual((self.sources / canonical / 'probe').read_text(), 'same file')

    def test_preserves_existing_directory_before_creating_any_links(self):
        old = self.root / 'drone-logistics'
        old.mkdir()
        (old / 'work.lua').write_text('preserve')
        with self.assertRaisesRegex(ValueError, 'Existing path preserved'):
            bind(self.root, self.sources)
        self.assertEqual((old / 'work.lua').read_text(), 'preserve')
        self.assertFalse((self.root / 'craftsystem').exists())

    def test_missing_sources_do_not_leave_partial_bindings(self):
        (self.sources / 'drone-logistics').rmdir()
        with self.assertRaisesRegex(ValueError, 'Missing source directory'):
            bind(self.root, self.sources)
        self.assertFalse((self.root / 'craftsystem').exists())
