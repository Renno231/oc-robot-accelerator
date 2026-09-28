"""Headless child creation must not allocate focus-stealing Windows consoles."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

import bootstrap
import runner_support
import supervisor


class ProcessVisibility(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows console policy')
    def test_build_and_process_inspection_children_are_hidden(self):
        child=Mock(); child.wait.return_value=0
        with patch.object(bootstrap.subprocess,'Popen',return_value=child) as launch, patch.object(supervisor,'_stop_tree'):
            bootstrap.run_checked(['unused'],timeout=1)
        flags=launch.call_args.kwargs['creationflags']
        self.assertTrue(flags & subprocess.CREATE_NO_WINDOW)
        self.assertTrue(flags & subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertIs(launch.call_args.kwargs.get('stdout'),sys.stdout)
        self.assertIs(launch.call_args.kwargs.get('stderr'),sys.stderr)
        completed=Mock(returncode=0,stdout=b'[]',stderr=b'')
        with patch.object(runner_support.subprocess,'run',return_value=completed) as inspect:
            self.assertEqual(runner_support._processes(set(),time.monotonic()+10),[])
        self.assertTrue(inspect.call_args.kwargs.get('creationflags',0) & subprocess.CREATE_NO_WINDOW)

    def test_every_current_spawn_selects_an_explicit_console_policy(self):
        root=Path(__file__).parent
        for path in sorted(root.glob('*.py')):
            if path.name==Path(__file__).name: continue
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                        and isinstance(node.func.value,ast.Name) and node.func.value.id=='subprocess'
                        and node.func.attr in ('Popen','run','check_call','check_output','call')):
                    with self.subTest(file=path.name,line=node.lineno):
                        self.assertIn('creationflags',{kw.arg for kw in node.keywords})

    @unittest.skipUnless(os.name == 'nt', 'Windows console policy')
    def test_hidden_child_has_no_console_and_preserves_output(self):
        code='import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())'
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=10,
                              creationflags=supervisor.NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'0')


if __name__=='__main__': unittest.main()
