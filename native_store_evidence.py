"""Decode native store.lua evidence; encoding remains owned by cbor.lua.

Lua strings (CBOR byte strings) are UTF-8 here, matching the JSON observer.
Log records are concatenated {k=key,v=value} maps; absent v deletes a key.
Directory stores contain one CBOR value per percent-escaped key filename.
"""
from io import BytesIO
from pathlib import Path
import struct
from urllib.parse import unquote


def decode(stream):
    def read(n):
        value = stream.read(n)
        if len(value) != n:
            raise ValueError('truncated CBOR')
        return value

    initial = read(1)[0]
    major, additional = initial >> 5, initial & 31
    if additional < 24:
        size = additional
    elif additional in (24, 25, 26, 27):
        raw = read(1 << (additional - 24))
        if major == 7 and additional in (25, 26, 27):
            return struct.unpack('>' + {25: 'e', 26: 'f', 27: 'd'}[additional], raw)[0]
        size = int.from_bytes(raw, 'big')
    else:
        raise ValueError('unsupported CBOR length: ' + str(additional))
    if major == 0:
        return size
    if major == 1:
        return -1 - size
    if major in (2, 3):
        return read(size).decode('utf-8')
    if major == 4:
        return [decode(stream) for _ in range(size)]
    if major == 5:
        result = {}
        for _ in range(size):
            key = decode(stream)
            result[key] = decode(stream)
        return result
    if major == 7 and size in (20, 21, 22):
        return {20: False, 21: True, 22: None}[size]
    raise ValueError('unsupported CBOR type: ' + str(major))


def value(data):
    stream = BytesIO(data)
    result = decode(stream)
    if stream.read(1):
        raise ValueError('trailing bytes after CBOR value')
    return result


def read_store(path):
    path = Path(path)
    if path.is_dir():
        return {unquote(entry.name, errors='strict'): value(entry.read_bytes())
                for entry in sorted(path.iterdir()) if entry.is_file()}
    result = {}
    with path.open('rb') as stream:
        while True:
            offset = stream.tell()
            if not stream.read(1):
                break
            stream.seek(offset)
            try:
                record = decode(stream)
                if 'v' in record:
                    result[record['k']] = record['v']
                else:
                    result.pop(record['k'], None)
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError(f'{path} at byte {offset}: {error}') from error
    return result


STORE_PATHS = ('/etc/warehouse.db', '/etc/warehouse.flight',
               '/etc/logistics.state', '/etc/mes.state')


def enrich(evidence, drive):
    files = evidence.setdefault('files', {})
    if files == []:
        files = evidence['files'] = {}
    for name in STORE_PATHS:
        path = Path(drive) / name.lstrip('/')
        if path.exists():
            files[name] = read_store(path)
    return evidence
