"""Versioned scenarios: strict local inputs, normalized engine contract and pristine copies."""
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re

from supervisor import _inventory, _no_link

MAX_TICKS = 1728000  # 24 simulated hours at 20 TPS; v1 retains its smaller limits.
MAX_TIMEOUT_SECONDS = 90000
OBSERVATION_BYTES = 32 * 1024 * 1024
MANIFEST_BYTES = 128 * 1024
PROGRAM_BYTES = 4 * 1024 * 1024
PROGRAM_FILE_BYTES = 1024 * 1024
PROGRAM_ENTRIES = 256
WORLD_BYTES = 256 * 1024 * 1024
WORLD_ENTRIES = 10000
REGISTRY = re.compile(r'[a-z0-9_.-]+:[a-z0-9_./-]+\Z')
PROPERTY = re.compile(r'[A-Za-z0-9_.+-]{1,64}\Z')
RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}


def _object(value, keys, required=()):
    if not isinstance(value, dict) or set(value) - set(keys) or set(required) - set(value):
        raise ValueError('object has unknown/missing keys; allowed=' + ','.join(keys))
    return value


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('integer outside ' + str(low) + '..' + str(high))
    return value


def _text(value, pattern, limit):
    if not isinstance(value, str) or len(value.encode('utf-8')) > limit or not pattern.fullmatch(value):
        raise ValueError('invalid or oversized string: ' + repr(value)[:128])
    return value


def _array(value, limit):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError('array count bound exceeded')
    return value


def relative(value):
    if not isinstance(value, str) or not value or len(value.encode('utf-8')) > 240:
        raise ValueError('bounded relative path required')
    for part in value.split('/'):
        if (not part or part in ('.', '..') or part[-1:] in ('.', ' ') or
                any(ord(c) < 32 or c in '\\:*?"<>|' for c in part) or
                part.split('.')[0].upper() in RESERVED):
            raise ValueError('unsafe relative path: ' + value)
    return value


def _position(value):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError('position must be [x,y,z]')
    return [_integer(value[0], -1000000, 1000000), _integer(value[1], 1, 254),
            _integer(value[2], -1000000, 1000000)]


def _inside(position, region):
    pos = _position(position)
    if any(not lo <= p <= hi for p, lo, hi in zip(pos, region['min'], region['max'])):
        raise ValueError('position outside scenario region')
    return pos


def _nbt(value):
    if not isinstance(value, str) or len(value.encode('utf-8')) > 4096:
        raise ValueError('SNBT byte bound exceeded')
    stack = []; quote = None; escaped = False
    for char in value:
        if quote:
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == quote: quote = None
        elif char in ('"', "'"): quote = char
        elif char in '[{':
            stack.append(char)
            if len(stack) > 16: raise ValueError('SNBT depth bound exceeded')
        elif char in ']}':
            if not stack or stack.pop() != ( '[' if char == ']' else '{'):
                raise ValueError('unbalanced SNBT')
    if quote or stack or not value.strip().startswith('{') or not value.strip().endswith('}'):
        raise ValueError('SNBT compound required')
    return value  # Registry-specific SNBT syntax is parsed by Minecraft, not reimplemented.


def _item(value, inventory=False, slots=16):
    keys = ['item', 'metadata', 'nbt'] + (['slot', 'count'] if inventory else [])
    _object(value, keys, ['item'] + (['slot', 'count'] if inventory else []))
    result = {'item': _text(value['item'], REGISTRY, 128),
              'metadata': _integer(value.get('metadata', 0), 0, 32767), 'nbt': _nbt(value.get('nbt', '{}'))}
    if inventory:
        result.update(slot=_integer(value['slot'], 1, slots), count=_integer(value['count'], 1, 64))
    return result


HARDWARE_FIELDS = ['tier', 'cpu', 'memory', 'cards', 'upgrades', 'storage', 'bootDrive', 'containers']


def _component_name(value):
    return _text(value, re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}\Z'), 64)


def _upgrade(value):
    if isinstance(value, str): return _component_name(value)
    _object(value, ['item', 'level', 'experience'], ['item'])
    if value['item'] != 'experienceupgrade' or ('level' in value) == ('experience' in value):
        raise ValueError('experienceupgrade configuration requires exactly one of level or experience')
    if 'level' in value:
        return {'item': 'experienceupgrade', 'level': _integer(value['level'], 0, 30)}
    xp = value['experience']
    if type(xp) not in (int, float) or not 0 <= xp <= 2147483647 or not math.isfinite(xp):
        raise ValueError('experience must be finite and in [0,2147483647]')
    return {'item': 'experienceupgrade', 'experience': xp}


def _hardware(value):
    _object(value, HARDWARE_FIELDS,
            ['tier', 'cpu', 'memory', 'storage', 'bootDrive'])
    tier = value['tier']
    result = {'tier': 'creative' if tier == 'creative' else _integer(tier, 1, 3),
              'cpu': _component_name(value['cpu'])}
    for key, limit in [('memory', 2), ('cards', 3), ('upgrades', 9), ('storage', 2)]:
        result[key] = [(_upgrade(name) if key == 'upgrades' else _component_name(name))
                       for name in _array(value.get(key, []), limit)]
    if not result['memory'] or not result['storage']:
        raise ValueError('hardware requires memory and a boot storage drive')
    result['bootDrive'] = _integer(value['bootDrive'], 0, len(result['storage']) - 1)
    result['containers'] = []
    for container in _array(value.get('containers', []), 3):
        _object(container, ['item', 'component'], ['item'])
        entry = {'item': _component_name(container['item'])}
        if 'component' in container: entry['component'] = _upgrade(container['component'])
        result['containers'].append(entry)
    return result


def normalize(value):
    """Pure shape/default owner. Input path existence is checked by load()."""
    _object(value, ['schemaVersion', 'id', 'program', 'world', 'robot', 'execution', 'observations', 'expect'],
            ['schemaVersion', 'id', 'program', 'world', 'robot'])
    version = _integer(value['schemaVersion'], 1, 3)
    logical_id = _text(value['id'], re.compile(r'[a-z][a-z0-9-]{0,62}\Z'), 63)
    program = _object(value['program'], ['directory', 'entry'], ['directory'])
    relative(program['directory'])
    entry = relative(program.get('entry', 'main.lua'))
    if not entry.endswith('.lua'): raise ValueError('entry must be a Lua file')
    world = _object(value['world'], ['region', 'blocks', 'source'], ['region'])
    bounds = _object(world['region'], ['min', 'max'], ['min', 'max'])
    region = {key: _position(bounds[key]) for key in ('min', 'max')}
    dimensions = [b - a + 1 for a, b in zip(region['min'], region['max'])]
    if any(d <= 0 for d in dimensions) or math.prod(dimensions) > 32768:
        raise ValueError('region cell bound exceeded or inverted region')
    if ((region['max'][0] // 16 - region['min'][0] // 16 + 1) *
            (region['max'][2] // 16 - region['min'][2] // 16 + 1)) > 64:
        raise ValueError('region chunk bound exceeded')
    blocks = []
    for block in _array(world.get('blocks', []), 128):
        _object(block, ['min', 'max', 'block', 'properties'], ['min', 'max', 'block'])
        low, high = _inside(block['min'], region), _inside(block['max'], region)
        if any(a > b for a, b in zip(low, high)): raise ValueError('inverted block volume')
        properties = block.get('properties', {})
        if not isinstance(properties, dict) or len(properties) > 16: raise ValueError('properties bound')
        properties = {_text(k, PROPERTY, 64): _text(v, PROPERTY, 64) for k, v in properties.items()}
        blocks.append({'min': low, 'max': high, 'block': _text(block['block'], REGISTRY, 128), 'properties': properties})
    normalized_world = {'region': region, 'blocks': blocks}
    if 'source' in world:
        relative(world['source']); normalized_world['source'] = 'world'
    robot = _object(value['robot'], ['position', 'facing', 'hardware', 'energy', 'tool', 'inventory'] +
                    (['randomSeed'] if version == 3 else []), ['position'])
    energy = robot.get('energy', 20000)
    energy_limit = 2147483647 if version == 3 else 50000
    if type(energy) not in (int, float) or not 0 < energy <= energy_limit or not math.isfinite(energy):
        raise ValueError('energy must be finite and in (0,' + str(energy_limit) + ']')
    facing = robot.get('facing', 'north')
    if facing not in ('north', 'south', 'east', 'west'):
        raise ValueError('unsupported facing')
    hardware = _hardware(robot.get('hardware')) if version == 3 else robot.get('hardware', 'tier3')
    if version < 3 and hardware != 'tier3': raise ValueError('unsupported legacy hardware')
    slots = 64 if version == 3 else 16
    inventory = [_item(item, True, slots) for item in _array(robot.get('inventory', []), slots)]
    if len({i['slot'] for i in inventory}) != len(inventory): raise ValueError('duplicate inventory slot')
    normalized_robot = {'position': _inside(robot['position'], region), 'facing': facing, 'hardware': hardware,
                        'energy': energy, 'tool': _item(robot.get('tool', {'item': 'minecraft:diamond_pickaxe'})),
                        'inventory': inventory}
    if 'randomSeed' in robot: normalized_robot['randomSeed'] = _integer(robot['randomSeed'], 0, 2147483647)
    execution = _object(value.get('execution', {}), ['mode', 'maxTicks', 'timeoutSeconds', 'executionDelayMillis', 'stallTicks'])
    mode = execution.get('mode', 'baseline' if version == 2 else 'coordinated')
    delay = execution.get('executionDelayMillis', 12)
    if mode not in (('baseline', 'coordinated', 'paced') if version == 3 else ('baseline', 'coordinated')) or type(delay) is not int or delay not in (0, 12):
        raise ValueError('unsupported mode/execution delay')
    tick_limit = 10000 if version == 1 else MAX_TICKS
    time_limit = 600 if version == 1 else MAX_TIMEOUT_SECONDS
    execution = {'mode': mode, 'executionDelayMillis': delay,
                 'maxTicks': _integer(execution.get('maxTicks', 10000), 1, tick_limit),
                 'timeoutSeconds': _integer(execution.get('timeoutSeconds', 120 if version == 1 else 600), 1, time_limit),
                 'stallTicks': _integer(execution.get('stallTicks', 0), 0, tick_limit)}
    observations = _object(value.get('observations', {}),
                           ['everyTicks'] if version == 1 else ['everyTicks', 'maxBytes', 'onFull'])
    normalized_observations = {'everyTicks': _integer(observations.get('everyTicks', 20), 1, 200)}
    if version >= 2:
        policy = observations.get('onFull', 'stop')
        if policy not in ('stop', 'fail'): raise ValueError('unsupported observation onFull policy')
        normalized_observations.update(maxBytes=_integer(observations.get('maxBytes', OBSERVATION_BYTES),
                                                        1024 * 1024, OBSERVATION_BYTES), onFull=policy)
    expect = _object(value.get('expect', {}), ['position', 'blocks', 'inventory'])
    expected_blocks = []
    for block in _array(expect.get('blocks', []), 256):
        _object(block, ['position', 'block'], ['position', 'block'])
        expected_blocks.append({'position': _inside(block['position'], region), 'block': _text(block['block'], REGISTRY, 128)})
    expected_inventory = []
    for item in _array(expect.get('inventory', []), 64):
        _object(item, ['item', 'minCount'], ['item', 'minCount'])
        expected_inventory.append({'item': _text(item['item'], REGISTRY, 128), 'minCount': _integer(item['minCount'], 0, 1024)})
    expectations = {'blocks': expected_blocks, 'inventory': expected_inventory}
    if 'position' in expect: expectations['position'] = _inside(expect['position'], region)
    normalized = {'schemaVersion': version, 'id': logical_id, 'program': {'directory': 'program', 'entry': entry},
            'world': normalized_world, 'robot': normalized_robot, 'execution': execution,
            'observations': normalized_observations, 'expect': expectations}
    normalized_bytes(normalized)  # Validate the exact bounded downstream representation too.
    return normalized


def normalized_bytes(value):
    data = (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'), sort_keys=True) + '\n').encode('utf-8')
    if len(data) > MANIFEST_BYTES: raise ValueError('normalized scenario byte bound exceeded')
    return data


def overlap(left, right):
    left, right = Path(left).resolve(), Path(right).resolve()
    return left == right or left in right.parents or right in left.parents


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def _json_bytes(path, limit):
    path = _no_link(path)
    if not path.is_file() or path.stat().st_size > limit: raise ValueError('JSON file byte bound exceeded')
    with path.open('rb') as inp: payload = inp.read(limit + 1)
    if len(payload) > limit: raise ValueError('JSON file byte bound exceeded')
    return payload


def _decode_json(payload):
    def reject_constant(value): raise ValueError('nonfinite JSON: ' + value)
    def finite_float(value):
        number=float(value)
        if not math.isfinite(number): reject_constant(value)
        return number
    try:
        return json.loads(payload.decode('utf-8'), object_pairs_hook=_pairs,
                          parse_constant=reject_constant, parse_float=finite_float)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('invalid JSON encoding/nesting') from exc


def read_json(path, limit=MANIFEST_BYTES):
    return _decode_json(_json_bytes(path, limit))


@dataclass(frozen=True)
class Scenario:
    manifest: Path
    original: bytes
    normalized: dict
    program: Path
    program_entries: tuple
    world: Path | None
    world_entries: tuple
    hardware_preset: bytes | None = None


def _resolve_hardware(value, root):
    """One local editable preset, shallow overrides; engine inputs are always the full recipe."""
    if not isinstance(value, dict) or value.get('schemaVersion') != 3: return value, None
    robot = value.get('robot')
    hardware = robot.get('hardware') if isinstance(robot, dict) else None
    if not isinstance(hardware, dict) or 'preset' not in hardware: return value, None
    _object(hardware, ['preset', 'overrides'], ['preset'])
    path = root / relative(hardware['preset'])
    payload = _json_bytes(path, MANIFEST_BYTES)
    base = _hardware(_decode_json(payload))  # Presets are complete recipes, not chains.
    overrides = _object(hardware.get('overrides', {}), HARDWARE_FIELDS)
    resolved = dict(value)
    resolved['robot'] = dict(robot, hardware=dict(base, **overrides))
    return resolved, payload


def _source(root, relative_path):
    path = root / relative(relative_path)
    try: path = _no_link(path)
    except OSError as exc: raise ValueError('missing input: ' + relative_path) from exc
    if not path.is_dir() or root not in path.parents: raise ValueError('input must be a scenario-local directory')
    return path


def _scan(root, byte_limit, entries, check):
    check()
    listing = _inventory(root, byte_limit, entries, check=check)
    names = set()
    for rel, _ in listing:
        relative(rel.as_posix())
        folded = rel.as_posix().casefold()
        if folded in names: raise ValueError('case-ambiguous input paths')
        names.add(folded)
    # Preserve empty directories too: a program may open an existing output directory.
    directory_entries = []
    def scan_error(exc): raise exc
    for parent, directories, _ in os.walk(root, onerror=scan_error):
        check()
        for directory in directories:
            rel = (Path(parent) / directory).relative_to(root)
            relative(rel.as_posix())
            folded = rel.as_posix().casefold()
            if folded in names: raise ValueError('case-ambiguous input paths')
            names.add(folded)
            directory_entries.append((rel, None))
    return tuple(directory_entries + listing)


def load(path, forbidden_roots=(), check=lambda: None, on_normalized=lambda value: None):
    check()
    try:
        manifest = _no_link(path)
        original = _json_bytes(manifest, MANIFEST_BYTES)
        value = _decode_json(original)
        resolved, hardware_preset = _resolve_hardware(value, manifest.parent)
        normalized = normalize(resolved)
        on_normalized(normalized)
        check()
        root = manifest.parent
        for other in forbidden_roots:
            if overlap(root, other): raise ValueError('scenario and output/template roots overlap')
        program = _source(root, value['program']['directory'])
        program_entries = _scan(program, PROGRAM_BYTES, PROGRAM_ENTRIES, check)
        if any(size is not None and size > PROGRAM_FILE_BYTES for _, size in program_entries): raise ValueError('program file byte bound exceeded')
        entry = program / normalized['program']['entry']
        if not entry.is_file(): raise ValueError('entry Lua file missing')
        _no_link(entry)
        world = _source(root, value['world']['source']) if 'source' in value['world'] else None
        world_entries = ()
        if world:
            if overlap(program, world): raise ValueError('program and world sources overlap')
            world_entries = _scan(world, WORLD_BYTES, WORLD_ENTRIES, check)
            if not (world / 'level.dat').is_file(): raise ValueError('source world must contain level.dat')
        check()
        return Scenario(manifest, original, normalized, program, program_entries, world, world_entries, hardware_preset)
    except TimeoutError:
        raise
    except (OSError, UnicodeError, RecursionError) as exc:
        raise ValueError('invalid scenario input: ' + str(exc)) from exc


def copy_tree(source, destination, entries, check=lambda: None):
    """Copy a previously bounded inventory and hash actual copied bytes, never links."""
    hashes = {}
    destination.mkdir(parents=True, exist_ok=False)
    for rel, size in entries:
        check()
        src = _no_link(source / rel)
        target = destination / rel
        if size is None:
            if not src.is_dir(): raise ValueError('input directory changed during copy')
            target.mkdir(parents=True, exist_ok=True)
            hashes[rel.as_posix() + '/'] = hashlib.sha256(b'').hexdigest()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(); used = 0
        with src.open('rb') as inp, target.open('xb') as out:
            while True:
                check()
                data = inp.read(1024 * 1024)
                if not data: break
                used += len(data)
                if used > size: raise ValueError('input changed during copy')
                out.write(data); digest.update(data)
        if used != size: raise ValueError('input changed during copy')
        hashes[rel.as_posix()] = digest.hexdigest()
    check()
    return hashes


def freeze(spec, destination, check=lambda: None):
    check()
    destination = Path(destination)
    if overlap(spec.manifest.parent, destination): raise ValueError('frozen inputs must be outside source')
    destination.mkdir(parents=True, exist_ok=False)
    hashes = {}
    manifests = [('scenario.json', spec.original), ('runner-scenario.json', normalized_bytes(spec.normalized))]
    if spec.hardware_preset is not None: manifests.append(('hardware-preset.json', spec.hardware_preset))
    for name, data in manifests:
        check(); (destination / name).write_bytes(data); hashes[name] = hashlib.sha256(data).hexdigest()
    for prefix, source, entries in [('program', spec.program, spec.program_entries), ('world', spec.world, spec.world_entries)]:
        if source is not None:
            hashes.update({prefix + '/' + name: sha for name, sha in copy_tree(source, destination / prefix, entries, check).items()})
    check()
    (destination / 'sha256.json').write_text(json.dumps(hashes, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return hashes
