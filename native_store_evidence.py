"""Decode native store.lua evidence; encoding remains owned by cbor.lua.

Lua strings (CBOR byte strings) are UTF-8 here, matching the JSON observer.
Log records are concatenated {k=key,v=value} maps; absent v deletes a key.
Directory stores contain one CBOR value per percent-escaped key filename.
"""
from io import BytesIO
from pathlib import Path
import struct
import math
import re
from urllib.parse import unquote


class LuaData:
    """Data-only OpenOS literals, consolidated from the native wire reporter.

    Parsing captures must never execute the Lua text they contain.
    """
    def __init__(self, text):
        if len(text.encode('utf8')) > 8 * 1024 * 1024:
            raise ValueError('data size bound')
        self.text, self.pos, self.nodes = text, 0, 0

    def space(self):
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def peek(self):
        self.space()
        return self.text[self.pos:self.pos + 1]

    def take(self, token):
        if self.peek() != token:
            raise ValueError('expected ' + token)
        self.pos += 1

    def string(self):
        quote = self.text[self.pos]; self.pos += 1
        out = []
        escapes = {'n': '\n', 'r': '\r', 't': '\t', 'a': '\a', 'b': '\b',
                   'f': '\f', 'v': '\v', '\\': '\\', '"': '"', "'": "'", '\n': '\n'}
        while self.pos < len(self.text):
            c = self.text[self.pos]; self.pos += 1
            if c == quote:
                return ''.join(out)
            if c == '\\':
                if self.pos >= len(self.text):
                    break
                c = self.text[self.pos]; self.pos += 1
                if c in '0123456789':
                    digits = c
                    while len(digits) < 3 and self.pos < len(self.text) and self.text[self.pos] in '0123456789':
                        digits += self.text[self.pos]; self.pos += 1
                    if int(digits) > 255:
                        raise ValueError('escape bound')
                    c = chr(int(digits))
                elif c == 'z':
                    self.space(); continue
                elif c in escapes:
                    c = escapes[c]
                else:
                    raise ValueError('unsupported string escape')
            out.append(c)
        raise ValueError('unterminated string')

    def value(self, depth=0):
        self.nodes += 1
        if depth > 32 or self.nodes > 100000:
            raise ValueError('data complexity bound')
        c = self.peek()
        if c in ('"', "'"):
            return self.string()
        if c == '{':
            self.pos += 1; table = {}; index = 1
            while self.peek() != '}':
                if not self.peek():
                    raise ValueError('unterminated table')
                if self.peek() == '[':
                    self.pos += 1; key = self.value(depth + 1)
                    if not isinstance(key, (str, int, float)) or isinstance(key, bool):
                        raise ValueError('invalid table key')
                    self.take(']'); self.take('=')
                else:
                    match = re.match(r'([A-Za-z_][A-Za-z_0-9]*)\s*=', self.text[self.pos:])
                    if match:
                        key = match[1]; self.pos += match.end()
                    else:
                        key = index; index += 1
                key = str(key)
                if key in table:
                    raise ValueError('duplicate table key')
                table[key] = self.value(depth + 1)
                if self.peek() in (',', ';'):
                    self.pos += 1
                elif self.peek() != '}':
                    raise ValueError('table separator')
            self.pos += 1
            return table
        nonfinite = re.match(r'(-inf|inf|nan)(?![A-Za-z_0-9])', self.text[self.pos:])
        if nonfinite:
            self.pos += nonfinite.end()
            return {'nonfinite': nonfinite[1]}
        match = re.match(r'(nil|true|false)(?![A-Za-z_0-9])|([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)', self.text[self.pos:])
        if not match:
            raise ValueError('unsupported literal at ' + str(self.pos))
        self.pos += match.end()
        if match[1]:
            return {'nil': None, 'true': True, 'false': False}[match[1]]
        value = float(match[2])
        if not math.isfinite(value):
            raise ValueError('nonfinite number')
        return int(value) if value.is_integer() else value

    def parse(self):
        value = self.value(); self.space()
        if self.pos != len(self.text):
            raise ValueError('trailing data/code')
        return value


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


STORE_PATHS = ('/etc/map.db', '/etc/warehouse.db', '/etc/warehouse.flight',
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
