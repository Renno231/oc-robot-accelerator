"""Owned loopback browser verification; no Minecraft server or external page needed.

Requires the developer playwright-cli command. The exported artifact itself has
no browser automation dependency. Select only an owned new output directory.
"""
import argparse
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import uuid

import runner_viewer as viewer
from supervisor import NO_WINDOW

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True); parser.add_argument('--jobs-root',required=True)
    parser.add_argument('--job',required=True)
    args=parser.parse_args(); output=Path(args.output).resolve(); output.mkdir(parents=True,exist_ok=False)
    cli=shutil.which('playwright-cli')
    if not cli: raise ValueError('playwright-cli required for developer browser verification')
    # Bypass the npm .cmd shell wrapper on Windows: multiline JavaScript must be
    # an exact argv value, not batch syntax. No browser/runtime dependency is shipped.
    prefix=[cli]
    if os.name=='nt':
        entry=Path(cli).parent/'node_modules/@playwright/cli/playwright-cli.js'
        if not entry.is_file(): raise ValueError('standard npm playwright-cli entrypoint required on Windows')
        prefix=[shutil.which('node') or 'node',str(entry)]
    session='ocrr-viewer-'+uuid.uuid4().hex[:8]
    calls=[]
    def command(*items):
        result=subprocess.run([*prefix,'-s='+session,*items],capture_output=True,text=True,encoding='utf-8',timeout=90,creationflags=NO_WINDOW)
        calls.append({'command':list(items),'exit':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        (output/'browser-commands.json').write_text(json.dumps(calls,indent=2),encoding='utf-8')
        if result.returncode or '### Error' in result.stdout: raise RuntimeError(result.stdout+result.stderr)
        return result.stdout
    actual=viewer.export(args.jobs_root,args.job,output/'actual.html')
    with tempfile.TemporaryDirectory(prefix='ocrr-viewer-') as temp:
        root=Path(temp)/'jobs'; job=root/('a'*32); runtime=job/'runtime'; runtime.mkdir(parents=True)
        robot={'position':[0,65,0],'facing':'north','energy':100,'state':'Sleeping','inventory':[],'tool':{}}
        cells=[{'position':[x,y,z],'block':'minecraft:air','properties':{}} for x in range(2) for y in (65,66) for z in range(2)]
        attack='</script><script>globalThis.INJECTED=true</script><img src="https://invalid.test/x">'
        cells[0]['block']=attack
        rows=[{'schemaVersion':1,'sequence':0,'tick':0,'kind':'initial','everyTicks':20,
               'region':{'min':[0,65,0],'max':[1,66,1]},'blocks':cells,'robot':robot},
              {'schemaVersion':1,'sequence':1,'tick':10,'kind':'sample',
               'blocks':[{'position':[0,65,1],'block':'minecraft:stone','properties':{}}],
               'robot':dict(robot,position=[1,65,0],energy=90)},
              {'schemaVersion':1,'sequence':2,'tick':40,'kind':'final','blocks':[],
               'robot':dict(robot,position=[1,66,0],energy=80,state='Stopped')}]
        path=runtime/'observations.ndjson'
        path.write_bytes((''.join(json.dumps(row)+'\n' for row in rows)).encode())
        (runtime/'program.log').write_text(attack,encoding='utf-8')
        viewer.export(root,job.name,output/'synthetic.html')
        path.write_bytes((json.dumps(rows[0])+'\n{partial').encode())
        viewer.export(root,job.name,output/'partial.html')
        cells=[{'position':[x,65,z],'block':'minecraft:air','properties':{}} for x in range(80) for z in range(100)]
        rows=[dict(rows[0],region={'min':[0,65,0],'max':[79,65,99]},blocks=cells),
              dict(rows[1],blocks=[dict(cell,block='minecraft:stone') for cell in cells])]
        path.write_bytes((''.join(json.dumps(row)+'\n' for row in rows)).encode())
        viewer.export(root,job.name,output/'stress.html')
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, format, *args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(output)))
    server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        command('open','about:blank','--headed')
        script=(HERE/'viewer/browser-check.js').read_text(encoding='utf-8')
        script=script.replace('__BASE_URL__',json.dumps('http://127.0.0.1:'+str(server.server_port)))
        script=script.replace('__SCREENSHOT__',json.dumps(str(output/'actual.png')))
        command('run-code',script)
        (output/'verification.json').write_text(json.dumps({'status':'passed','actual':actual,
            'htmlSha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob('*.html')},
            'note':'Loopback serving is a developer browser-harness accommodation; exported files need no service.'},indent=2))
    finally:
        try: command('close')
        finally: server.shutdown(); server.server_close(); thread.join(timeout=5)
    print(json.dumps({'status':'passed','output':str(output)}))


if __name__=='__main__': main()
