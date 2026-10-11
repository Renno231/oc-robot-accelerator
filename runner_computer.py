"""Shape-only contract for a finite-powered v4 OpenOS case and placed OC blocks."""
import math


def number(value, label, low=0):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= 2147483647:
        raise ValueError(label + ' must be finite and in [' + str(low) + ',2147483647]')
    return value


def normalize(value, region, directory='program'):
    from runner_scenario import _object, _integer, _component_name, _array, _inside, relative
    _object(value, ['kind', 'position', 'hardware', 'program'], ['position', 'hardware', 'program'])
    kind = value.get('kind', 'case')
    if kind not in ('case', 'rack'): raise ValueError('controller kind must be case or rack')
    rack = kind == 'rack'
    h = _object(value['hardware'], ['tier', 'cpu', 'memory', 'cards', 'storage', 'bootDrive'] + (['buses'] if rack else []),
                ['tier', 'cpu', 'memory', 'storage', 'bootDrive'])
    hardware = {'tier': _integer(h['tier'], 1, 3), 'cpu': _component_name(h['cpu'])}
    for key, limit in [('memory', 4 if rack else 2), ('cards', 4 if rack else 3), ('storage', 4 if rack else 2)] + ([('buses', 3)] if rack else []):
        hardware[key] = [_component_name(n) for n in _array(h.get(key, []), limit)]
    if not hardware['memory'] or not hardware['storage']: raise ValueError('computer requires memory and storage')
    hardware['bootDrive'] = _integer(h['bootDrive'], 0, len(hardware['storage']) - 1)
    p = _object(value['program'], ['directory', 'entry'], ['directory'])
    relative(p['directory']); entry = relative(p.get('entry', 'main.lua'))
    if not entry.endswith('.lua'): raise ValueError('computer entry must be a Lua file')
    result = {'position': _inside(value['position'], region), 'hardware': hardware,
              'program': {'directory': directory, 'entry': entry}}
    if 'kind' in value: result['kind'] = kind
    if rack:
        x, y, z = result['position']
        _inside([x-1, y, z], region); _inside([x-1, y+1, z], region)
    return result


def blocks(values, region):
    from runner_scenario import _object, _array, _inside, _text, REGISTRY, PROPERTY
    result = []
    for b in _array(values, 128):
        _object(b, ['position', 'block', 'properties', 'energy'], ['position', 'block'])
        props = b.get('properties', {})
        if not isinstance(props, dict) or len(props) > 16: raise ValueError('properties bound')
        entry = {'position': _inside(b['position'], region), 'block': _text(b['block'], REGISTRY, 128),
                 'properties': {_text(k, PROPERTY, 64): _text(v, PROPERTY, 64) for k, v in props.items()}}
        if 'energy' in b: entry['energy'] = number(b['energy'], 'block energy')
        result.append(entry)
    if len({tuple(b['position']) for b in result}) != len(result): raise ValueError('duplicate placed block position')
    return result


def expectation(value, entry):
    if 'minEnergy' in value: entry['minEnergy'] = number(value['minEnergy'], 'minimum drone energy')
    if 'running' in value:
        if type(value['running']) is not bool: raise ValueError('drone running must be boolean')
        entry['running'] = value['running']
