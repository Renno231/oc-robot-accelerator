"""Scenario-driven, bounded local Minecraft/OpenComputers robot jobs."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

import runner_jobs as jobs
import runner_observations as observations
import runner_scenario as scenario

HERE=Path(__file__).resolve().parent


def _parser():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='operation',required=True)
    commands.add_parser('init',help='create a mining example in a new directory').add_argument('path')
    commands.add_parser('validate',help='validate inputs without starting a server').add_argument('scenario')
    run=commands.add_parser('run',help='freeze inputs and start an owned job')
    run.add_argument('scenario'); run.add_argument('--jobs-root',required=True); run.add_argument('--java')
    run.add_argument('--installation')
    run.add_argument('--template')
    run.add_argument('--control-jar')
    run.add_argument('--detach',action='store_true')
    setup=commands.add_parser('setup',help='install a pinned runtime without a development build')
    setup.add_argument('--installation',required=True); setup.add_argument('--java',required=True)
    setup.add_argument('--timeout',type=float,default=900); setup.add_argument('--accept-eula',action='store_true')
    doctor=commands.add_parser('doctor',help='read-only installed artifact and Java checks')
    doctor.add_argument('--installation',required=True); doctor.add_argument('--java')
    for name in ('status','wait','cancel','observations','inspect','recover','cleanup','diagnostics','view'):
        command=commands.add_parser(name)
        command.add_argument('job'); command.add_argument('--jobs-root',required=True)
        if name=='wait': command.add_argument('--timeout',type=float,default=600)
        if name=='recover': command.add_argument('--confirm-processes-stopped',action='store_true')
        if name=='cleanup': command.add_argument('--confirm-delete-runtime',action='store_true')
        if name in ('diagnostics','view'): command.add_argument('--output',required=True)
        if name=='diagnostics': command.add_argument('--include-observations',action='store_true')
    return parser


def _initialize(path):
    target=Path(path).absolute()
    # Require a wholly new target; never overlay or overwrite caller-owned files.
    target.mkdir(parents=True,exist_ok=False)
    try:
        source=HERE/'examples/mining'
        for entry in source.iterdir():
            if entry.is_dir(): shutil.copytree(entry,target/entry.name)
            else: shutil.copyfile(entry,target/entry.name)
    except BaseException:
        shutil.rmtree(target)
        raise
    return {'status':'created','scenario':str(target/'scenario.json')}


def _dispatch(args):
    if args.operation in ('setup','doctor'):
        import runner_setup
        value=(runner_setup.install(args.installation,args.java,args.timeout,accept_eula=args.accept_eula)
               if args.operation=='setup' else runner_setup.doctor(args.installation,args.java))
        return value,0 if value['status']=='ready' else 1
    if args.operation=='view':
        import runner_viewer
        return runner_viewer.export(args.jobs_root,args.job,args.output),0
    if args.operation in ('inspect','recover','cleanup','diagnostics'):
        import runner_support
        if args.operation=='inspect': return runner_support.inspect(args.jobs_root,args.job),0
        if args.operation=='recover':
            return runner_support.recover(args.jobs_root,args.job,confirm_stopped=args.confirm_processes_stopped),0
        if args.operation=='cleanup':
            return runner_support.cleanup(args.jobs_root,args.job,confirm_delete_runtime=args.confirm_delete_runtime),0
        return runner_support.diagnostics(args.jobs_root,args.job,args.output,
                                          include_observations=args.include_observations),0
    if args.operation=='init': return _initialize(args.path),0
    if args.operation=='validate':
        spec=scenario.load(args.scenario)
        return {'status':'valid','scenario':spec.normalized,
                'programFiles':sum(size is not None for _,size in spec.program_entries),
                'worldFiles':sum(size is not None for _,size in spec.world_entries)},0
    if args.operation=='run':
        value=None
        try:
            if args.installation:
                if args.template or args.control_jar: raise ValueError('--installation excludes --template/--control-jar')
                import runner_setup
                paths=runner_setup.resolve(args.installation,args.java)
                value=jobs.submit(args.scenario,args.jobs_root,paths['java'],paths['template'],paths['control_jar'],
                                  runtime_libraries=paths['runtime_libraries'],control_identity=paths['control_identity'])
            else:
                if not args.java: raise ValueError('Developer run requires --java; packaged runs may use --installation')
                value=jobs.submit(args.scenario,args.jobs_root,args.java,args.template or str(HERE/'.cache/server'),
                                  args.control_jar or str(HERE/'build/libs/robot-spike.jar'))
            if not args.detach and value['state'] not in jobs.TERMINAL:
                value=jobs.wait_foreground(args.jobs_root,value['jobId'])
        except KeyboardInterrupt as exc:
            jobid=exc.jobid if isinstance(exc,jobs.SubmissionInterrupted) else (value or {}).get('jobId')
            if jobid is None: raise
            jobs.cancel(args.jobs_root,jobid)
            try: value=jobs.wait(args.jobs_root,jobid,timeout=10)
            except TimeoutError: value=jobs.status(args.jobs_root,jobid)
            return value,130
    elif args.operation=='status': value=jobs.status(args.jobs_root,args.job)
    elif args.operation=='wait': value=jobs.wait(args.jobs_root,args.job,timeout=args.timeout)
    elif args.operation=='cancel': value=jobs.cancel(args.jobs_root,args.job)
    else:
        job=jobs._job(args.jobs_root,args.job)
        return observations.summary(job/'runtime/observations.ndjson'),0
    return value,1 if value['state'] in ('failed','cancelled','unavailable') else 0


def main(argv=None):
    args=_parser().parse_args(argv)
    try:
        value,code=_dispatch(args)
        data=json.dumps(value,sort_keys=True,allow_nan=False)
    except KeyboardInterrupt:
        data=json.dumps({'status':'error','error':'KeyboardInterrupt','message':'interrupted; inspect jobs root for retained owner'}); code=130
    except (ValueError,TypeError,OSError,TimeoutError,RuntimeError,subprocess.SubprocessError) as exc:
        data=json.dumps({'status':'error','error':type(exc).__name__,'message':str(exc)[:4096]}); code=1
    if len(data.encode('utf-8'))>256*1024:
        data=json.dumps({'status':'error','message':'CLI JSON output bound exceeded; inspect owned artifact files'}); code=1
    print(data)
    return code


if __name__=='__main__': sys.exit(main())
