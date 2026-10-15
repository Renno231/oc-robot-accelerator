"""Schema-four shape contract. Native recipes and capacities remain OC-owned."""
import math
from copy import deepcopy

MAX_DRONES = 16


def eeprom_inputs(root, drones, check):
    from pathlib import Path
    from runner_scenario import relative, PROGRAM_FILE_BYTES
    from supervisor import _no_link
    entries = {}; names = {}
    for drone in drones:
        check()
        rel = relative(drone['eeprom'])
        parts = rel.split('/')
        for i in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:i]); folded = prefix.casefold()
            if folded in names and names[folded] != prefix:
                raise ValueError('case-ambiguous EEPROM paths')
            names[folded] = prefix
        file = _no_link(root / rel)
        if not file.is_file() or root not in file.parents:
            raise ValueError('scenario-local EEPROM file required')
        size = file.stat().st_size
        if size > PROGRAM_FILE_BYTES: raise ValueError('EEPROM input byte bound')
        entries[Path(rel)] = size
    return tuple(entries.items())


def completed_result(value, scenario_id, count, computer_present=False, second_present=False, robot_count=0, microcontroller_count=0):
    drones = value.get('drones')
    if (value.get('runnerSchemaVersion') != 1 or value.get('scenarioId') != scenario_id or
            value.get('mode') not in ('baseline','coordinated') or not isinstance(drones, list) or len(drones) != count or
            any(not isinstance(d, dict) or type(d.get('index')) is not int or d['index'] != i or
                (not computer_present and d.get('state') != 'Stopped') or 'lastError' not in d or d['lastError'] is not None or d.get('observedError') is not None
                for i, d in enumerate(drones))):
        raise ValueError('runner result identity/drone completion invalid')
    if computer_present:
        c = value.get('computer')
        if (not isinstance(c, dict) or c.get('lastError') is not None or
                not isinstance(value.get('program'), dict) or value['program'].get('status') != 'returned'):
            raise ValueError('runner computer program completion invalid')
    if second_present:
        c=value.get('secondComputer')
        if (not isinstance(c,dict) or c.get('lastError') is not None or
                not isinstance(c.get('program'),dict) or c['program'].get('status')!='returned'):
            raise ValueError('runner second computer completion invalid')
    if robot_count:
        robots = value.get('robots')
        if (not isinstance(robots, list) or len(robots) != robot_count or
                any(not isinstance(r, dict) or type(r.get('index')) is not int or r['index'] != i or
                    not isinstance(r.get('state'), str) or
                    (not computer_present and r.get('state') != 'Stopped') or
                    'lastError' not in r or r['lastError'] is not None or
                    not isinstance(r.get('program'), dict) or
                    r['program'].get('status') not in (('returned', 'not_returned') if computer_present else ('returned',)) or
                    (r.get('state') == 'Stopped' and r['program'].get('status') != 'returned')
                    for i, r in enumerate(robots))):
            raise ValueError('runner robot program completion invalid')
    if microcontroller_count:
        sensors = value.get('microcontrollers')
        if (not isinstance(sensors, list) or len(sensors) != microcontroller_count or
                any(not isinstance(s, dict) or type(s.get('index')) is not int or s['index'] != i or
                    type(s.get('running')) is not bool or 'lastError' not in s or s['lastError'] is not None
                    for i, s in enumerate(sensors))):
            raise ValueError('runner microcontroller completion invalid')


def observation(record):
    from runner_observations import _position
    drones = record['drones']
    if not isinstance(drones, list) or not (0 if 'computer' in record or 'robots' in record else 1) <= len(drones) <= MAX_DRONES:
        raise ValueError('invalid drone observation count')
    for i, d in enumerate(drones):
        if not isinstance(d, dict) or type(d.get('index')) is not int or d['index'] != i:
            raise ValueError('invalid drone observation index')
        p = d.get('position')
        if (not isinstance(p, list) or len(p) != 3 or
                any(type(n) not in (int, float) or not math.isfinite(n) for n in p)):
            raise ValueError('invalid exact drone observation position')
        _position(d.get('blockPosition'))
        energy = d.get('energy')
        if type(energy) not in (int, float) or not math.isfinite(energy) or energy < 0:
            raise ValueError('invalid drone observation energy')
    if 'microcontrollers' in record:
        sensors = record['microcontrollers']
        if not isinstance(sensors, list) or not 1 <= len(sensors) <= 16: raise ValueError('invalid microcontroller observation count')
        for i, s in enumerate(sensors):
            if not isinstance(s, dict) or type(s.get('index')) is not int or s['index'] != i or type(s.get('running')) is not bool:
                raise ValueError('invalid microcontroller observation')
            _position(s.get('position'))
            energy = s.get('energy')
            if type(energy) not in (int, float) or not math.isfinite(energy) or energy < 0:
                raise ValueError('invalid microcontroller energy')
    if 'robots' in record:
        robots = record['robots']
        if not isinstance(robots, list) or not 1 <= len(robots) <= 4: raise ValueError('invalid robot observation count')
        for i, r in enumerate(robots):
            if not isinstance(r, dict) or type(r.get('index')) is not int or r['index'] != i:
                raise ValueError('invalid robot observation index')
            _position(r.get('position'))
            if r.get('facing') not in ('north', 'south', 'east', 'west'): raise ValueError('invalid robot facing')
            energy = r.get('energy')
            if type(energy) not in (int, float) or not math.isfinite(energy) or energy < 0:
                raise ValueError('invalid robot observation energy')


def slots(values, initial=False, limit=64):
    from runner_scenario import _array, _object, _integer, _text, REGISTRY, _item
    result = []
    for value in _array(values, limit):
        if initial:
            entry = _item(value, True, limit)
        else:
            _object(value, ['slot', 'item', 'count'], ['slot', 'count'])
            entry = {'slot': _integer(value['slot'], 1, limit), 'count': _integer(value['count'], 0, 64)}
            if 'item' in value: entry['item'] = _text(value['item'], REGISTRY, 128)
            if entry['count'] and 'item' not in entry: raise ValueError('nonempty slot requires item')
        result.append(entry)
    if len({v['slot'] for v in result}) != len(result): raise ValueError('duplicate inventory slot')
    return result


def normalize(value):
    from runner_computer import normalize as computer, blocks as placed_blocks, expectation
    from runner_scenario import (_object, _array, _inside, _integer, _text, REGISTRY, PROPERTY,
                                 _component_name, relative, normalize as old, normalized_bytes)
    if isinstance(value, dict) and 'controller' in value:
        if 'computer' in value: raise ValueError('use controller or computer, not both')
        _object(value['controller'], ['kind', 'position', 'hardware', 'program'], ['kind', 'position', 'hardware', 'program'])
        value = deepcopy(value)
        value['computer'] = value.pop('controller')
    _object(value, ['schemaVersion', 'id', 'program', 'world', 'robot', 'drones', 'containers',
                    'execution', 'observations', 'expect', 'computer', 'secondComputer', 'blocks', 'robots', 'containerEdits', 'droneActions', 'microcontrollers'], ['schemaVersion', 'id', 'world'])
    if 'secondComputer' in value and 'computer' not in value: raise ValueError('secondComputer requires computer')
    if ('robot' in value) == ('drones' in value or 'computer' in value): raise ValueError('v4 requires robot or drones/computer exclusively')
    drone_mode = 'drones' in value or 'computer' in value
    if 'robots' in value and not drone_mode: raise ValueError('robots require drones/computer scenario')
    if 'microcontrollers' in value and (not drone_mode or 'computer' not in value): raise ValueError('microcontrollers require controller computer')
    if drone_mode and 'program' in value: raise ValueError('drone scenarios use EEPROM, not program')
    surrogate = deepcopy(value)
    surrogate['schemaVersion'] = 3
    for key in ('drones', 'containers', 'computer', 'secondComputer', 'blocks', 'robots', 'containerEdits', 'droneActions', 'microcontrollers'): surrogate.pop(key, None)
    extended = _object(value.get('expect', {}), ['position', 'blocks', 'inventory', 'containers', 'drones', 'robots'])
    if 'robots' in extended and 'robots' not in value: raise ValueError('robot expectations require robots')
    if drone_mode and any(k in extended for k in ('position', 'inventory')):
        raise ValueError('drone expectations use expect.drones')
    if not drone_mode and 'drones' in extended: raise ValueError('drone expectations require drones')
    surrogate['expect'] = {k: v for k, v in extended.items() if k not in ('drones', 'containers', 'robots')}
    execution = _object(surrogate.get('execution', {}), ['mode', 'maxTicks', 'timeoutSeconds', 'executionDelayMillis', 'stallTicks', 'infiniteEnergy'])
    if 'infiniteEnergy' in execution:
        if type(execution['infiniteEnergy']) is not bool: raise ValueError('infiniteEnergy must be boolean')
        surrogate['execution'].pop('infiniteEnergy')
    if 'blocks' in value:
        surrogate.setdefault('execution', {}).setdefault('mode', 'baseline')
    if drone_mode:
        surrogate['program'] = {'directory': 'program'}
        surrogate['robot'] = {'position': value['world']['region']['min'],
                              'hardware': {'tier': 1, 'cpu': 'cpu1', 'memory': ['ram1'],
                                           'storage': ['hdd1'], 'bootDrive': 0}}
        surrogate.setdefault('execution', {}).setdefault('mode', 'baseline')
        if surrogate['execution']['mode'] not in ('baseline','coordinated'): raise ValueError('drone scenarios require baseline or coordinated mode')
    result = old(surrogate)
    result['schemaVersion'] = 4
    if 'infiniteEnergy' in value.get('execution', {}):
        result['execution']['infiniteEnergy'] = value['execution']['infiniteEnergy']
    region = result['world']['region']
    drones = []
    microcontrollers = []
    if drone_mode:
        del result['robot']; del result['program']
        devices = [(d, True) for d in _array(value.get('drones', []), MAX_DRONES)]
        devices += [(d, False) for d in _array(value.get('microcontrollers', []), 16)]
        for d, is_drone in devices:
            _object(d, ['position', 'hardware', 'eeprom', 'eepromData', 'energy'] + (['inventory'] if is_drone else []),
                    ['position', 'hardware', 'eeprom'])
            h = _object(d['hardware'], ['tier', 'cpu', 'memory', 'cards', 'upgrades'], ['tier', 'cpu', 'memory'])
            hardware = {'tier': 'creative' if h['tier'] == 'creative' else _integer(h['tier'], 1, 2),
                        'cpu': _component_name(h['cpu'])}
            for key, limit in [('memory', 2), ('cards', 3), ('upgrades', 9)]:
                hardware[key] = [_component_name(n) for n in _array(h.get(key, []), limit)]
            if not hardware['memory']: raise ValueError('drone hardware requires memory')
            eeprom = relative(d['eeprom'])
            if not eeprom.endswith('.lua'): raise ValueError('EEPROM must be a Lua file')
            data = d.get('eepromData', '')
            if not isinstance(data, str) or len(data.encode('utf-8')) > 1024 * 1024:
                raise ValueError('EEPROM data string bound')
            entry = {'position': _inside(d['position'], region), 'hardware': hardware,
                     'eeprom': eeprom, 'eepromData': data}
            if is_drone: entry['inventory'] = slots(d.get('inventory', []), True, 8)
            relative(entry['eeprom'])
            if 'energy' in d:
                energy = d['energy']
                if type(energy) not in (int, float) or not math.isfinite(energy) or not 0 < energy <= 2147483647:
                    raise ValueError('drone energy must be finite and positive')
                entry['energy'] = energy
            (drones if is_drone else microcontrollers).append(entry)
        if not drones and 'computer' not in value and 'robots' not in value: raise ValueError('drones must contain 1..16 entries')
        result['drones'] = drones
        if 'microcontrollers' in value: result['microcontrollers'] = microcontrollers
    if 'robots' in value:
        robots = _array(value['robots'], 4)
        if not robots: raise ValueError('robots must contain 1..4 entries')
        result['robots'] = []
        for i, r in enumerate(robots):
            _object(r, ['position', 'facing', 'hardware', 'program', 'inventory', 'energy', 'assembly'], ['position', 'hardware', 'program'])
            legacy = deepcopy(surrogate)
            legacy['robot'] = {k: v for k, v in r.items() if k not in ('program', 'assembly')}
            legacy['program'] = r['program']; legacy['expect'] = {}
            normalized = old(legacy)
            robot = normalized['robot']; robot.pop('tool')
            robot['program'] = dict(normalized['program'], directory=f'robot-program-{i}')
            if 'assembly' in r:
                if i == 0 or i != len(robots)-1: raise ValueError('assembly must add the last robot to an existing factory')
                a = _object(r['assembly'], ['source', 'blocks', 'request'], ['source', 'blocks', 'request'])
                for block in _array(a['blocks'], 128):
                    _object(block, ['position', 'block', 'properties'], ['position', 'block'])
                source = _inside(a['source'], region)
                if source not in [c['position'] for c in value.get('containers', [])]: raise ValueError('assembly source must be declared')
                req = _object(a['request'], ['computer', 'marker', 'signal'], ['computer', 'marker', 'signal'])
                index = _integer(req['computer'], 0, 1)
                if ('computer' if index == 0 else 'secondComputer') not in value: raise ValueError('assembly controller absent')
                robot['assembly'] = {'source': source, 'blocks': placed_blocks(a['blocks'], region),
                                     'request': {'computer': index, 'marker': relative(req['marker']),
                                                 'signal': _text(req['signal'], PROPERTY, 64)}}
            result['robots'].append(robot)
        if len({tuple(r['position']) for r in result['robots']}) != len(robots): raise ValueError('duplicate robot position')
        result['expect']['robots'] = []
        for r in _array(extended.get('robots', []), 4):
            _object(r, ['index', 'inventory'], ['index'])
            entry = {'index': _integer(r['index'], 0, len(robots) - 1)}
            if 'inventory' in r: entry['inventory'] = slots(r['inventory'], limit=85)
            result['expect']['robots'].append(entry)
    if 'computer' in value: result['computer'] = computer(value['computer'], region)
    if 'secondComputer' in value:
        result['secondComputer']=computer(value['secondComputer'],region,'second-program')
        if result['secondComputer']['position']==result['computer']['position']: raise ValueError('duplicate computer position')
    if 'blocks' in value: result['blocks'] = placed_blocks(value['blocks'], region)
    containers = []
    for c in _array(value.get('containers', []), 128):
        _object(c, ['position', 'block', 'slots', 'properties'], ['position', 'block', 'slots'])
        containers.append({'position': _inside(c['position'], region), 'block': _text(c['block'], REGISTRY, 128),
                           'slots': slots(c['slots'], True)})
        if 'properties' in c:
            props=c['properties']
            if not isinstance(props,dict) or len(props)>16: raise ValueError('properties bound')
            containers[-1]['properties']={_text(k,PROPERTY,64):_text(v,PROPERTY,64) for k,v in props.items()}
    if len({tuple(c['position']) for c in containers}) != len(containers): raise ValueError('duplicate container position')
    result['containers'] = containers
    if 'containerEdits' in value:
        if not drone_mode: raise ValueError('container edits require drones/computer scenario')
        result['containerEdits'] = []
        for edit in _array(value['containerEdits'], 64):
            _object(edit, ['position', 'slot', 'count', 'atTick', 'request', 'expectedCount'], ['position', 'slot', 'count'])
            if ('atTick' in edit) == ('request' in edit): raise ValueError('container edit requires exactly one trigger')
            p = _inside(edit['position'], region)
            if p not in [c['position'] for c in containers]: raise ValueError('container edit target must be declared')
            entry = {'position': p, 'slot': _integer(edit['slot'], 1, 64), 'count': _integer(edit['count'], 1, 64)}
            if 'expectedCount' in edit:
                entry['expectedCount'] = _integer(edit['expectedCount'], entry['count'], 64)
            if 'atTick' in edit: entry['atTick'] = _integer(edit['atTick'], 0, result['execution']['maxTicks'])
            else:
                req = _object(edit['request'], ['computer', 'marker', 'signal'], ['computer', 'marker', 'signal'])
                index = _integer(req['computer'], 0, 1)
                if ('computer' if index == 0 else 'secondComputer') not in value: raise ValueError('container edit computer absent')
                entry['request'] = {'computer': index, 'marker': relative(req['marker']),
                                    'signal': _text(req['signal'], PROPERTY, 64)}
            result['containerEdits'].append(entry)
    if 'droneActions' in value:
        if not drone_mode: raise ValueError('drone actions require drone mode')
        result['droneActions'] = []
        for action in _array(value['droneActions'], 64):
            _object(action, ['action', 'drone', 'to', 'request'], ['action', 'drone', 'to', 'request'])
            if action['action'] != 'move_drone': raise ValueError('unknown drone action')
            req = _object(action['request'], ['computer', 'marker', 'signal'], ['computer', 'marker', 'signal'])
            index = _integer(req['computer'], 0, 1)
            if ('computer' if index == 0 else 'secondComputer') not in value: raise ValueError('drone action computer absent')
            result['droneActions'].append({'action': 'move_drone',
                'drone': _integer(action['drone'], 0, len(drones) - 1),
                'to': _inside(action['to'], region),
                'request': {'computer': index, 'marker': relative(req['marker']),
                            'signal': _text(req['signal'], PROPERTY, 64)}})
    result['expect']['containers'] = []
    assembly_positions = [b['position'] for r in result.get('robots', []) if 'assembly' in r for b in r['assembly']['blocks']]
    for c in _array(extended.get('containers', []), 128):
        _object(c, ['position', 'slots'], ['position', 'slots'])
        p = _inside(c['position'], region)
        if p not in [c['position'] for c in containers] + assembly_positions: raise ValueError('expect container must be declared')
        result['expect']['containers'].append({'position': p, 'slots': slots(c['slots'])})
    if drone_mode:
        result['expect'].pop('inventory', None)
        result['expect']['drones'] = []
        for d in _array(extended.get('drones', []), MAX_DRONES):
            _object(d, ['index', 'blockPosition', 'inventory', 'minEnergy', 'running'], ['index'])
            entry = {'index': _integer(d['index'], 0, len(drones) - 1)}
            if 'blockPosition' in d: entry['blockPosition'] = _inside(d['blockPosition'], region)
            if 'inventory' in d: entry['inventory'] = slots(d['inventory'], limit=8)
            expectation(d, entry)
            result['expect']['drones'].append(entry)
    normalized_bytes(result)
    return result
