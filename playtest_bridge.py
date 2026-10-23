"""Drive a computer's screen in a running world through playtest_bridge.lua.

The computer runs `bridge` (playtest_bridge.lua as /usr/bin/bridge.lua); this
writes key commands onto its disk folder and reads the screen dumps back.

    python playtest_bridge.py DISK install          copy the bridge onto the disk
    python playtest_bridge.py DISK read [--colors]  print the screen
    python playtest_bridge.py DISK key enter down shift+right c
    python playtest_bridge.py DISK type "mesui craft"

DISK is the computer's folder, world/opencomputers/<address>.
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

# LWJGL key codes, as OpenOS's keyboard library names them.
CODES = {'escape': 1, 'backspace': 14, 'tab': 15, 'enter': 28, 'space': 57,
         'up': 200, 'down': 208, 'left': 203, 'right': 205, 'home': 199, 'end': 207,
         'pageup': 201, 'pagedown': 209, 'delete': 211, 'shift': 42, 'ctrl': 29}
CHARS = {'backspace': 8, 'tab': 9, 'enter': 13, 'space': 32, 'escape': 27}
ROW = {**{c: 16 + i for i, c in enumerate('qwertyuiop')}, **{c: 30 + i for i, c in enumerate('asdfghjkl')},
       **{c: 44 + i for i, c in enumerate('zxcvbnm')}, **{str(d): 1 + d for d in range(1, 10)}, '0': 11,
       '-': 12, '=': 13, '[': 26, ']': 27, ';': 39, "'": 40, ',': 51, '.': 52, '/': 53, '\\': 43, ' ': 57}
SHIFTED = {'_': '-', '+': '=', '{': '[', '}': ']', ':': ';', '"': "'", '<': ',', '>': '.', '?': '/', '|': '\\',
           '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8', '(': '9', ')': '0'}


class Bridge:
    def __init__(self, disk):
        self.dir = Path(disk) / 'home' / '.bridge'
        self.inbox = self.dir / 'in'

    def send(self, lines):
        if not self.inbox.is_dir():
            sys.exit('no bridge inbox at %s: run `bridge` on the computer' % self.inbox)
        name = str(time.time_ns())
        tmp = self.dir / ('.' + name)
        tmp.write_text('\n'.join(lines) + '\n')
        tmp.replace(self.inbox / name)

    def keys(self, names):
        lines = []
        for spec in names:
            parts = spec.lower().split('+')
            mods, key = parts[:-1], parts[-1]
            code = CODES.get(key) or ROW.get(key)
            if code is None:
                sys.exit('unknown key ' + spec)
            char = CHARS.get(key, ord(key) if len(key) == 1 else 0)
            if 'shift' in mods and len(key) == 1:
                char = ord(key.upper())
            lines += ['down 0 %d' % CODES[m] for m in mods]
            lines += ['down %d %d' % (char, code), 'up %d %d' % (char, code)]
            lines += ['up 0 %d' % CODES[m] for m in reversed(mods)]
        self.send(lines)

    def type(self, text):
        lines = []
        for ch in text:
            if ch == '\n':
                lines += ['down 13 28', 'up 13 28']
                continue
            base = SHIFTED.get(ch, ch.lower())
            code = ROW.get(base, 0)
            shift = ch in SHIFTED or ch.isupper()
            if shift: lines.append('down 0 42')
            lines += ['down %d %d' % (ord(ch), code), 'up %d %d' % (ord(ch), code)]
            if shift: lines.append('up 0 42')
        self.send(lines)

    def read(self, timeout=15):
        screen = self.dir / 'screen'
        before = screen.stat().st_mtime_ns if screen.exists() else 0
        self.send(['dump'])
        deadline = time.time() + timeout
        while time.time() < deadline:
            if screen.exists() and screen.stat().st_mtime_ns != before:
                try:
                    lines = screen.read_text(encoding='utf-8').split('\n')
                    w, h = map(int, lines[0].split())
                    if len(lines) >= 1 + 2 * h:
                        return [(lines[1 + 2 * y], lines[2 + 2 * y]) for y in range(h)]
                except (OSError, ValueError):
                    pass
            time.sleep(0.1)
        error = self.dir / 'error'
        sys.exit('no screen dump within %ds%s' % (timeout, (': ' + error.read_text()) if error.exists() else ''))


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser()
    p.add_argument('disk')
    p.add_argument('command', choices=['install', 'read', 'key', 'type'])
    p.add_argument('args', nargs='*')
    p.add_argument('--colors', action='store_true', help='print each row\'s colour runs under it')
    p.add_argument('--wait', type=float, default=0.5, help='seconds to wait after keys before returning')
    a = p.parse_args()
    b = Bridge(a.disk)
    if a.command == 'install':
        target = Path(a.disk) / 'usr' / 'bin' / 'bridge.lua'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).with_name('playtest_bridge.lua'), target)
        print('installed', target)
    elif a.command == 'read':
        for text, runs in b.read():
            print(text.rstrip())
            if a.colors: print('   ', runs)
    elif a.command == 'key':
        b.keys(a.args); time.sleep(a.wait)
    else:
        b.type(' '.join(a.args)); time.sleep(a.wait)


if __name__ == '__main__':
    main()
