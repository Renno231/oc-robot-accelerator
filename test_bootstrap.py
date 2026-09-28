import hashlib
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
import bootstrap


class BootstrapTest(unittest.TestCase):
    def test_existing_artifact_verified_without_network(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'file'; path.write_bytes(b'checked')
            with patch('bootstrap.subprocess.run') as run:
                bootstrap.acquire(path, 'https://invalid.example/file', hashlib.sha256(b'checked').hexdigest())
                run.assert_not_called()
            with self.assertRaises(ValueError):
                bootstrap.acquire(path, 'https://invalid.example/file', '0' * 64)
            self.assertEqual(b'checked', path.read_bytes())

    def test_nested_acquisition_rejects_ancestor_link_before_read_or_download(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cache=root/'cache';cache.mkdir();outside=root/'outside';outside.mkdir()
            link=cache/'runtime-libraries'
            if os.name=='nt':
                subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)],check=True,capture_output=True,creationflags=bootstrap.NO_WINDOW)
            else: link.symlink_to(outside,target_is_directory=True)
            try:
                def download(command,**kwargs):
                    Path(command[command.index('--output')+1]).write_bytes(b'pinned')
                with patch('bootstrap.run_checked',side_effect=download) as run:
                    with self.assertRaises(ValueError):
                        bootstrap.acquire(link/'logging.jar','https://invalid.example/logging.jar',hashlib.sha256(b'pinned').hexdigest())
                    run.assert_not_called()
                self.assertEqual(list(outside.iterdir()),[])
                (outside/'logging.jar').write_bytes(b'pinned')
                with patch('bootstrap.sha256') as digest:
                    with self.assertRaises(ValueError):
                        bootstrap.acquire(link/'logging.jar','https://invalid.example/logging.jar',hashlib.sha256(b'pinned').hexdigest())
                    digest.assert_not_called()
            finally:
                if os.name=='nt':link.rmdir()
                else:link.unlink()

    def test_extraction_rejects_traversal_and_expansion(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); archive = root / 'test.zip'
            for entry in ('../outside', '/absolute', 'C:/outside', 'safe/../../outside'):
                with zipfile.ZipFile(archive, 'w') as z: z.writestr(entry, b'x')
                with self.assertRaises(ValueError): bootstrap.unpack(archive, root / 'out')
            with zipfile.ZipFile(archive, 'w') as z: z.writestr('safe/file', b'1234')
            with self.assertRaises(ValueError): bootstrap.unpack(archive, root / 'out', limit=3)
            bootstrap.unpack(archive, root / 'out')
            self.assertEqual(b'1234', (root / 'out/safe/file').read_bytes())

    def test_extracted_distribution_rechecked(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); archive = root / 'test.zip'
            with zipfile.ZipFile(archive, 'w') as z: z.writestr('safe/file', b'1234')
            bootstrap.unpack(archive, root / 'out')
            bootstrap.verify_distribution(archive, root / 'out')
            (root / 'out/safe/file').write_bytes(b'4321')
            with self.assertRaises(ValueError): bootstrap.verify_distribution(archive, root / 'out')

    def test_profile_pins_all_base_runtime_artifacts(self):
        names = {entry['name'] for entry in bootstrap.ARTIFACTS}
        self.assertEqual({'gradle-4.9-bin.zip', 'forge-installer.jar', 'OpenComputers-1.8.9a.jar'}, names)
        for entry in bootstrap.ARTIFACTS:
            self.assertEqual(64, len(entry['sha256']))
            self.assertTrue(entry['url'].startswith('https://'))


if __name__ == '__main__': unittest.main()
