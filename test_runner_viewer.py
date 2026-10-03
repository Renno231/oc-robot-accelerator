"""Offline replay is sampled data, never game execution or interpolated state."""
import base64
import contextlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import runner
import runner_viewer as viewer
from test_runner_observations import records


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'jobs'; self.id='a'*32
        self.job=self.root/self.id; self.runtime=self.job/'runtime'; self.runtime.mkdir(parents=True)
        self.path=self.runtime/'observations.ndjson'; self.output=Path(self.tmp.name)/'replay.html'
        self.store(records())

    def store(self, rows):
        self.path.write_bytes((''.join(json.dumps(row)+'\n' for row in rows)).encode())

    def payload(self):
        html=self.output.read_text(encoding='utf-8')
        encoded=re.search(r'<script id="recording" type="application/octet-stream">([A-Za-z0-9+/=]+)</script>',html)[1]
        return html,json.loads(base64.b64decode(encoded))

    def test_export_complete_data_without_html_execution_or_source_changes(self):
        attack='</script><script>globalThis.INJECTED=true</script><img src=https://invalid.test/x>'
        rows=records(); rows[0]['blocks'][0]['block']=attack; self.store(rows)
        (self.runtime/'program.log').write_text(attack)
        (self.runtime/'result.json').write_text(json.dumps({'reason':attack,'passed':False}))
        before=self.path.read_bytes()
        result=viewer.export(self.root,self.id,self.output)
        html,data=self.payload()
        self.assertEqual('exported',result['status']); self.assertEqual(2,result['records'])
        self.assertEqual(attack,data['records'][0]['blocks'][0]['block'])
        self.assertEqual(attack,data['console']['text']); self.assertNotIn(attack,html)
        self.assertIn("connect-src 'none'",html); self.assertIn("default-src 'none'",html)
        self.assertNotIn('src="http',html); self.assertIn('Robot replay',html)
        self.assertTrue(data['summary']['finalRecorded']); self.assertEqual(before,self.path.read_bytes())
        self.assertEqual('unavailable',data['job']['state'])

    def test_partial_record_and_missing_final_are_explicit(self):
        self.store(records()[:1]); self.path.write_bytes(self.path.read_bytes()+b'{partial')
        viewer.export(self.root,self.id,self.output); _,data=self.payload()
        self.assertEqual(1,len(data['records'])); self.assertTrue(data['summary']['truncatedLastLine'])
        self.assertFalse(data['summary']['finalRecorded']); self.assertEqual('missing',data['summary']['coverageStatus'])

    def test_empty_malformed_and_viewer_bounds_never_create_output(self):
        for kind in ('empty','invalid','record-cap','cell-cap','byte-cap'):
            with self.subTest(kind=kind):
                self.store(records())
                if kind=='empty': self.path.write_bytes(b'')
                if kind=='invalid': self.path.write_bytes(b'{}\n')
                settings={'MAX_RECORDS':1} if kind=='record-cap' else {'MAX_CELLS':1} if kind=='cell-cap' else {'OUTPUT_BYTES':50} if kind=='byte-cap' else {}
                with patch.multiple(viewer,**settings) if settings else contextlib.nullcontext():
                    with self.assertRaises(ValueError): viewer.export(self.root,self.id,self.output)
                self.assertFalse(self.output.exists())

    def test_unsafe_browser_coordinates_are_rejected(self):
        for axis,value in ((0,2**60),(1,-1)):
            rows=records()
            for row in rows:
                row['robot']['position'][axis]=value
                for cell in row['blocks']: cell['position'][axis]=value
            rows[0]['region']['min'][axis]=value; rows[0]['region']['max'][axis]=value
            self.store(rows)
            with self.subTest(axis=axis),self.assertRaisesRegex(ValueError,'coordinate'):
                viewer.export(self.root,self.id,self.output)
            self.assertFalse(self.output.exists())

    def test_exclusive_destination_and_job_containment(self):
        self.output.write_text('keep')
        with self.assertRaises(FileExistsError): viewer.export(self.root,self.id,self.output)
        self.assertEqual('keep',self.output.read_text())
        with self.assertRaisesRegex(ValueError,'outside'):
            viewer.export(self.root,self.id,self.job/'viewer.html')

    def test_console_tail_metadata_and_bad_result_remain_visible(self):
        (self.runtime/'program.log').write_bytes(b'a'*(viewer.CONSOLE_BYTES+5))
        (self.runtime/'result.json').write_text('{partial')
        viewer.export(self.root,self.id,self.output); _,data=self.payload()
        self.assertTrue(data['console']['truncated']); self.assertEqual(5,data['console']['offset'])
        self.assertEqual('invalid',data['result']['status']); self.assertEqual(viewer.CONSOLE_BYTES,len(data['console']['text']))

    def test_cli_view_does_not_launch_or_wait_for_engine(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out),patch('runner.jobs.submit',side_effect=AssertionError('no server')):
            code=runner.main(['view',self.id,'--jobs-root',str(self.root),'--output',str(self.output)])
        self.assertEqual(0,code); self.assertEqual('exported',json.loads(out.getvalue())['status'])


if __name__=='__main__': unittest.main()
