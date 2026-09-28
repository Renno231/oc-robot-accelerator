"""Bounded reconstruction of recorded samples; never a deterministic resimulation."""
from pathlib import Path
import runner_scenario as scenario
import supervisor

MAX_BYTES=32*1024*1024
MAX_LINE=8*1024*1024
STATUS_BYTES=64*1024


def _coverage(path):
    """Read a bounded checkpoint, not a substitute for the retained record stream."""
    try:
        temporary=path.with_name('.observations-status.json.tmp')
        try:
            if supervisor._no_link(temporary).stat().st_size>STATUS_BYTES:
                raise ValueError('coverage temporary byte bound exceeded')
        except FileNotFoundError:
            pass  # Atomic publication may remove the temporary file during inspection.
        try:
            value=scenario.read_json(path.with_name('observations-status.json'),STATUS_BYTES)
        except FileNotFoundError:
            return None,'missing'
        fields={'schemaVersion','policy','maxBytes','bytesWritten','recordsWritten',
                'lastRecordedTick','lastObservedTick','recordingStopped','stopReason','finalRecorded'}
        if not isinstance(value,dict) or set(value)!=fields:
            raise ValueError('coverage fields invalid')
        for key in ('schemaVersion','maxBytes','bytesWritten','recordsWritten'):
            if type(value[key])!=int or value[key]<0: raise ValueError('coverage counter invalid')
        for key in ('lastRecordedTick','lastObservedTick'):
            if value[key] is not None and (type(value[key])!=int or value[key]<0):
                raise ValueError('coverage tick invalid')
        for key in ('recordingStopped','finalRecorded'):
            if type(value[key])!=bool: raise ValueError('coverage flag invalid')
        if (value['schemaVersion']!=1 or value['policy'] not in ('stop','fail') or
                not 1048576<=value['maxBytes']<=MAX_BYTES or
                not value['recordsWritten']<=value['bytesWritten']<=value['maxBytes']):
            raise ValueError('coverage schema/policy/bytes invalid')
        recorded,observed=value['lastRecordedTick'],value['lastObservedTick']
        if value['recordsWritten']==0:
            if value['bytesWritten']!=0 or recorded is not None or value['finalRecorded']:
                raise ValueError('empty coverage invalid')
        elif recorded is None or observed is None or observed<recorded:
            raise ValueError('coverage tick ordering invalid')
        if value['recordingStopped']:
            if value['policy']!='stop' or value['stopReason']!='byte_limit' or value['finalRecorded']:
                raise ValueError('stopped coverage invalid')
        elif value['stopReason'] is not None:
            raise ValueError('coverage stop reason invalid')
        return value,'ahead'  # Reconcile with complete NDJSON records below.
    except (OSError,ValueError):
        return None,'invalid'


def _checkpoint_matches(value, info):
    return (value['recordsWritten']==info['records'] and
            value['bytesWritten']==info['bytesRecorded'] and
            value['lastRecordedTick']==info.get('lastTick') and
            value['finalRecorded']==info['finalRecorded'])


def _position(value):
    if not isinstance(value,list) or len(value)!=3 or any(type(n)!=int for n in value):
        raise ValueError('invalid observation position')
    return tuple(value)


def reconstruct(path, *, max_bytes=MAX_BYTES, max_line=MAX_LINE, on_record=None):
    path=Path(path)
    checkpoint,coverage_status=_coverage(path)
    info={'available':False,'path':str(path.absolute()),'records':0,'truncatedLastLine':False,'finalRecorded':False,
          'bytesRead':0,'bytesRecorded':0,'observationCoverage':checkpoint,'coverageStatus':coverage_status,
          'coverage':'sampled region blocks and robot only; excludes transient changes and entity/block-entity state'}
    prefix_matches=checkpoint is not None and _checkpoint_matches(checkpoint,info)
    if prefix_matches: info['coverageStatus']='consistent'
    result={'summary':info,'blocks':{},'last':None}
    if not path.exists(): return result
    path=supervisor._no_link(path)
    if not path.is_file() or path.stat().st_size>max_bytes: raise ValueError('observation file byte bound exceeded')
    total=0; region=None; previous_tick=-1
    with path.open('rb') as stream:
        while True:
            raw=stream.readline(max_line+1)
            if not raw: break
            total+=len(raw)
            if total>max_bytes or len(raw)>max_line: raise ValueError('observation file/line byte bound exceeded')
            if not raw.endswith(b'\n'):
                info['truncatedLastLine']=True; break
            record=scenario._decode_json(raw)
            sequence=info['records']
            if (not isinstance(record,dict) or type(record.get('schemaVersion'))!=int or record['schemaVersion']!=1 or
                type(record.get('sequence'))!=int or record['sequence']!=sequence or
                type(record.get('tick'))!=int or record['tick']<previous_tick or
                record['tick']<0 or record.get('kind') not in ('initial','sample','final') or info['finalRecorded']):
                raise ValueError('invalid observation sequence/tick/kind')
            if sequence==0:
                if record['kind']!='initial': raise ValueError('initial observation missing')
                region=record.get('region')
                if not isinstance(region,dict): raise ValueError('initial region missing')
                low,high=_position(region.get('min')),_position(region.get('max'))
                volume=1
                for lo,hi in zip(low,high):
                    if lo>hi: raise ValueError('invalid region')
                    volume*=hi-lo+1
                if volume>32768: raise ValueError('region bound exceeded')
                cadence=record.get('everyTicks')
                if type(cadence)!=int or not 1<=cadence<=200: raise ValueError('invalid sample cadence')
                info.update(region=region,everyTicks=cadence,firstTick=record['tick'])
            elif record['kind']=='initial': raise ValueError('duplicate initial record')
            cells=record.get('blocks')
            if not isinstance(cells,list) or len(cells)>volume: raise ValueError('invalid block samples')
            updates={}
            for cell in cells:
                if not isinstance(cell,dict): raise ValueError('invalid block sample')
                position=_position(cell.get('position'))
                if any(not lo<=n<=hi for n,lo,hi in zip(position,low,high)) or position in updates:
                    raise ValueError('block sample outside region or duplicated')
                if not isinstance(cell.get('block'),str) or not isinstance(cell.get('properties'),dict):
                    raise ValueError('invalid block state')
                updates[position]=cell
            if sequence==0 and len(updates)!=volume: raise ValueError('initial record does not cover region')
            robot=record.get('robot')
            if not isinstance(robot,dict): raise ValueError('robot observation missing')
            _position(robot.get('position'))
            result['blocks'].update(updates); result['last']=record
            previous_tick=record['tick']
            info.update(available=True,records=sequence+1,lastTick=record['tick'],lastKind=record['kind'],
                        finalRecorded=record['kind']=='final',lastRobot=robot,bytesRecorded=total)
            if checkpoint is not None and _checkpoint_matches(checkpoint,info): prefix_matches=True
            if on_record is not None: on_record(record)
    info['bytesRead']=total
    if checkpoint is not None:
        info['coverageStatus']=('consistent' if _checkpoint_matches(checkpoint,info)
                                else 'stale' if (prefix_matches and not checkpoint['recordingStopped']
                                                 and info['bytesRecorded']<=checkpoint['maxBytes'])
                                else 'ahead')
    return result


def summary(path):
    return reconstruct(path)['summary']
