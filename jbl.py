#!/usr/bin/env python3
"""Control a JBL Live 770NC from the terminal over Bluetooth LE.

Protocol reverse-engineered from Android HCI snoop logs of the JBL Headphones
app (capture*/btsnoop_hci.log). Frames are `aa <cmd> <len> <payload>` written
to WRITE; replies arrive as notifications on NOTIFY. The EQ reply uses a
16-bit little-endian length. Simple setters are acknowledged with
`aa 00 02 <cmd> 00`.

Not supported: voice-prompt language. The app downloads a voice pack over an
encrypted Classic Bluetooth channel, not over this protocol.
"""
import argparse, asyncio, struct, sys
from bleak import BleakClient, BleakScanner

NAME_PREFIX = 'JBL Live 770NC'
NOTIFY = '65786365-6c70-6f69-6e74-2e636f6d0001'
WRITE = '65786365-6c70-6f69-6e74-2e636f6d0002'

ON_OFF = {'on': 1, 'off': 0}

# --- noise control (0x91): TLV 01=ANC 02=Ambient Aware 03=TalkThru
NC = {'anc': (1, 0, 0), 'ambient': (0, 1, 0), 'talkthru': (0, 0, 1)}

# --- equalizer (0xa2): preset id + 10 band gains in dB (float32)
EQ_FREQS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
EQ_PRESETS = {
    'off':          (0x00, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    'jazz':         (0x01, [4, 3, 1, 2.5, -1.5, -1.5, 0, 1, 3, 4]),
    'vocal':        (0x02, [-1.5, -3, -3, 1, 3.5, 3.5, 3, 1.5, 0, -1.5]),
    'bass':         (0x03, [4, 4, 3, 2.5, 0.5, 0, 0, 0, 0, 0]),
    'club':         (0x06, [2, 1.5, 1, 0, 0, 0, 0, 1, 1, 2]),
    'studio':       (0x07, [-2, -1, -1, -0.5, 0, 0, 0, 0, 0, 0]),
    'extreme-bass': (0x09, [4, 4.5, 4.5, 3.5, -1, 0, 0, 2, 2, 0]),
}

def eq_frame(preset_id, gains):
    p = bytearray([0x03, preset_id, 0, 0, 0, 0, 0x30] + [0] * 8)
    for g, f in zip(gains, EQ_FREQS):
        p += bytes([0x0a, 0x01]) + struct.pack('<ff', g, f)
    p += b'\x0a'
    return bytes([0xaa, 0xa2]) + struct.pack('<H', len(p)) + p

# --- spatial sound (0x9d): <enabled> <mode>
SPATIAL = {'music': 1, 'movie': 2, 'game': 3}

# --- single-press gesture (0x77 key 06): which modes the button cycles through
SINGLE_PRESS = {
    'anc-ambient': 0x0b,
    'anc-ambient-off': 0x09,
    'ambient-off': 0x0d,
    'anc-off': 0x0c,
}

# --- voice aware (0x98): <level> <enabled>
VOICE_AWARE_LEVELS = {'low': 1, 'mid': 2, 'high': 3}

# --- smart audio & video (0x81 set / 0x82 get): opaque 8-byte settings
SMART_AV = {
    'audio': bytes.fromhex('0001350096 00ffff'.replace(' ', '')),
    'video': bytes.fromhex('c5002e006400ffff'),
    'off':   bytes.fromhex('00012e00b400ffff'),
}

# --- voice assistant: gesture key 0e + setting 0x34 (read back via 0x21 0x35)
ASSISTANT = {'native': (0xa1, 0xdf), 'google': (0xa4, 0x01), 'alexa': (0xa6, 0x02)}

# --- voice prompt language, as reported by 0x93 01 01 (read only)
LANGUAGES = {0x01: 'english', 0x0b: 'spanish'}

AUTO_OFF = {'30': 30, '60': 60, '120': 120, '30m': 30, '1h': 60, '2h': 120}

def name_of(table, value, default=None):
    for k, v in table.items():
        if v == value:
            return k
    return default if default is not None else f'unknown({value!r})'

def tlv(p):
    return dict(zip(p[0::2], p[1::2]))


class JBL:
    def __init__(self, client):
        self.c = client
        self.q = asyncio.Queue()

    async def start(self):
        await self.c.start_notify(NOTIFY, lambda _, d: self.q.put_nowait(bytes(d)))

    @staticmethod
    def payload(msg):
        if msg[1] == 0xa2 and len(msg) >= 4:
            n = struct.unpack('<H', msg[2:4])[0]
            return msg[4:4 + n]
        return msg[3:3 + msg[2]]

    async def ask(self, frame, reply_cmd, match=None, timeout=4.0):
        """Write frame; return payload of the first notification from reply_cmd
        whose payload starts with `match` (bytes)."""
        while not self.q.empty():
            self.q.get_nowait()
        await self.c.write_gatt_char(WRITE, frame, response=True)
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while (left := end - loop.time()) > 0:
            try:
                msg = await asyncio.wait_for(self.q.get(), left)
            except asyncio.TimeoutError:
                break
            if len(msg) < 3 or msg[0] != 0xaa:
                continue
            if msg[1] == 0xee and len(msg) > 3 and msg[3] == frame[1]:
                raise RuntimeError(f'headphones rejected command {frame[1]:#04x}')
            if msg[1] == reply_cmd:
                p = self.payload(msg)
                if match is None or p.startswith(match):
                    return p
        raise TimeoutError('no reply to ' + frame.hex(' '))

    async def send(self, *payload_cmd, ack=None, match=None):
        frame = bytes([0xaa, payload_cmd[0], len(payload_cmd) - 1, *payload_cmd[1:]])
        return await self.ask(frame, ack if ack is not None else payload_cmd[0], match)

    async def set_simple(self, cmd, *args):
        """Setters acknowledged with `aa 00 02 <cmd> 00`."""
        await self.send(cmd, *args, ack=0x00, match=bytes([cmd]))

    # ---- getters
    async def noise_control(self):
        t = tlv((await self.send(0x91, 0x11, match=b'\x12'))[1:])
        return name_of(NC, (t.get(1, 0), t.get(2, 0), t.get(3, 0)), 'off')

    async def eq(self):
        p = await self.ask(bytes.fromhex('aaa20201ff'), 0xa2, match=b'\x04')
        return name_of({k: v[0] for k, v in EQ_PRESETS.items()}, p[1])

    async def dynamic_eq(self):
        return (await self.send(0x9e, 0x01))[1]

    async def spatial(self):
        p = await self.send(0x9d, 0x01)
        return name_of(SPATIAL, p[2]) if p[1] else 'off'

    async def gestures(self):
        return tlv((await self.send(0x77, 0x01, 0xff))[1:])

    async def voice_aware(self):
        p = await self.send(0x98, 0x01)
        return p[1], p[2]  # level, enabled

    async def smart_av(self):
        p = await self.send(0x82, ack=0x83)
        return name_of(SMART_AV, bytes(p), f'custom({p.hex()})')

    async def psa(self):
        t = tlv((await self.send(0xa0, 0x01))[1:])
        return t[1], t[2], t[3]  # enabled, balance(100=centre), gain 1-5

    async def balance(self):
        t = tlv((await self.send(0xa8, 0x01))[1:])
        return t[1], t[2]  # enabled, value(100=centre)

    async def assistant(self):
        v = (await self.send(0x21, 0x35, ack=0x22, match=b'\x35'))[1]
        return name_of({k: v[1] for k, v in ASSISTANT.items()}, v)

    async def prompts(self):
        on = (await self.send(0x93, 0x04, match=b'\x05'))[1]
        lang = (await self.send(0x93, 0x01, match=b'\x02'))[1]
        return on, LANGUAGES.get(lang, f'unknown({lang:#04x})')

    async def volume_limit(self):
        return (await self.send(0xa5, 0x01))[2]

    async def battery(self):
        return (await self.send(0x25, 0x00))[3]

    async def auto_off(self):
        p = await self.send(0x21, 0x30, ack=0x22, match=b'\x30')
        return p[10], struct.unpack('<H', p[11:13])[0]  # enabled, minutes

    async def serial(self):
        return (await self.send(0x94, 0x01))[1:].decode(errors='replace').strip()



def balance_byte(s):
    v = int(s)
    if not -15 <= v <= 15:
        raise argparse.ArgumentTypeError('balance is -15 (left) .. 15 (right)')
    return 100 + v


async def run(a, j):
    cmd = a.cmd or 'status'
    onoff = lambda v: 'on' if v else 'off'
    if cmd in NC:
        await j.send(0x91, 0x10, 1, NC[cmd][0], 2, NC[cmd][1], 3, NC[cmd][2], match=b'\x12')
        print(await j.noise_control())
    elif cmd == 'off':
        await j.send(0x91, 0x13, match=b'\x12')
        print(await j.noise_control())
    elif cmd == 'eq':
        pid, gains = EQ_PRESETS[a.preset]
        await j.ask(eq_frame(pid, gains), 0xa2, match=b'\x04')
        print('eq:', await j.eq())
    elif cmd == 'dynamic-eq':
        await j.send(0x9e, 0x00, ON_OFF[a.state])
        print('low-volume dynamic EQ:', onoff(await j.dynamic_eq()))
    elif cmd == 'spatial':
        if a.mode == 'off':
            cur = await j.send(0x9d, 0x01)
            await j.send(0x9d, 0x00, 0, cur[2] or 1)
        else:
            await j.send(0x9d, 0x00, 1, SPATIAL[a.mode])
        print('spatial sound:', await j.spatial())
    elif cmd == 'single-press':
        await j.send(0x77, 0x00, 0x06, SINGLE_PRESS[a.cycle])
        print('single press:', name_of(SINGLE_PRESS, (await j.gestures()).get(6)))
    elif cmd == 'voice-aware':
        level, _ = await j.voice_aware()
        if a.level == 'off':
            await j.send(0x98, 0x00, level, 0)
        else:
            await j.send(0x98, 0x00, VOICE_AWARE_LEVELS[a.level], 1)
        level, on = await j.voice_aware()
        print('voice aware:', name_of(VOICE_AWARE_LEVELS, level) if on else 'off')
    elif cmd == 'smart-av':
        await j.ask(bytes([0xaa, 0x81, 8]) + SMART_AV[a.mode], 0x83)
        print('smart audio & video:', a.mode, '(headphones reconnect)')
    elif cmd == 'autoplay':
        await j.set_simple(0x35, ON_OFF[a.state])
        print('auto play & pause:', a.state)
    elif cmd == 'psa':
        on, bal, gain = await j.psa()
        if a.state:
            on = ON_OFF[a.state]
        if a.balance is not None:
            bal = a.balance
        if a.gain is not None:
            gain = a.gain
        await j.send(0xa0, 0x00, 1, on, 2, bal, 3, gain)
        on, bal, gain = await j.psa()
        print(f'personal sound amplification: {onoff(on)}, balance {bal - 100:+d}, gain {gain}')
    elif cmd == 'balance':
        on, val = await j.balance()
        if a.value == 'off':
            on = 0
        elif a.value == 'on':
            on = 1
        else:
            on, val = 1, balance_byte(a.value)
        await j.send(0xa8, 0x00, 1, on, 2, val)
        on, val = await j.balance()
        print(f'left/right balance: {onoff(on)}, {val - 100:+d}')
    elif cmd == 'assistant':
        key, val = ASSISTANT[a.which]
        g = await j.gestures()
        if a.which == 'alexa':
            await j.send(0x92, 0x00, 0x02, 0x01)
        await j.send(0x77, 0x00, 0x09, g.get(9, 0x0a), 0x0a, g.get(10, 0x05), 0x0e, key, 0x0b, g.get(11, 0x06))
        await j.set_simple(0x34, val)
        print('voice assistant:', a.which, '(headphones restart)')
    elif cmd == 'prompts':
        await j.send(0x93, 0x03, ON_OFF[a.state], ack=0x93, match=b'\x05')
        on, lang = await j.prompts()
        print(f'voice prompts: {onoff(on)} ({lang})')
    elif cmd == 'volume-limit':
        await j.send(0xa5, 0x00, 0x01, ON_OFF[a.state])
        print('max volume limiter:', onoff(await j.volume_limit()))
    elif cmd == 'auto-off':
        if a.time == 'off':
            await j.set_simple(0x33, 0, 120, 0)
        else:
            await j.set_simple(0x33, 1, AUTO_OFF[a.time], 0)
        on, mins = await j.auto_off()
        print('auto power off:', f'{mins} min' if on else 'off')
    elif cmd == 'battery':
        print(f'{await j.battery()}%')
    elif cmd == 'info':
        print('serial:', await j.serial())
    elif cmd == 'raw':
        while not j.q.empty():
            j.q.get_nowait()
        await j.c.write_gatt_char(WRITE, bytes.fromhex(a.hex), response=True)
        await asyncio.sleep(1.5)
        while not j.q.empty():
            print(j.q.get_nowait().hex(' '))
    elif cmd == 'status':
        g = await j.gestures()
        level, va = await j.voice_aware()
        psa_on, psa_bal, psa_gain = await j.psa()
        bal_on, bal = await j.balance()
        p_on, lang = await j.prompts()
        ao, mins = await j.auto_off()
        rows = [
            ('battery', f'{await j.battery()}%'),
            ('noise control', await j.noise_control()),
            ('eq', await j.eq()),
            ('low-volume dynamic EQ', onoff(await j.dynamic_eq())),
            ('spatial sound', await j.spatial()),
            ('single press', name_of(SINGLE_PRESS, g.get(6))),
            ('voice aware', name_of(VOICE_AWARE_LEVELS, level) if va else 'off'),
            ('smart audio & video', await j.smart_av()),
            ('personal sound amp', f'{onoff(psa_on)}, balance {psa_bal - 100:+d}, gain {psa_gain}'),
            ('left/right balance', f'{onoff(bal_on)}, {bal - 100:+d}'),
            ('voice assistant', await j.assistant()),
            ('voice prompts', f'{onoff(p_on)} ({lang})'),
            ('max volume limiter', onoff(await j.volume_limit())),
            ('auto power off', f'{mins} min' if ao else 'off'),
        ]
        w = max(len(k) for k, _ in rows)
        for k, v in rows:
            print(f'{k:<{w}}  {v}')


def parser():
    ap = argparse.ArgumentParser(description='Control a JBL Live 770NC over Bluetooth LE.')
    sub = ap.add_subparsers(dest='cmd', metavar='command')
    sub.add_parser('status', help='show every setting (default)')
    sub.add_parser('anc', help='noise cancelling on')
    sub.add_parser('ambient', help='Ambient Aware on')
    sub.add_parser('talkthru', help='TalkThru on')
    sub.add_parser('off', help='noise control off')
    sub.add_parser('eq', help='equalizer preset').add_argument('preset', choices=EQ_PRESETS)
    sub.add_parser('dynamic-eq', help='low-volume dynamic EQ').add_argument('state', choices=ON_OFF)
    sub.add_parser('spatial', help='spatial sound').add_argument('mode', choices=['off', *SPATIAL])
    sub.add_parser('single-press', help='modes the noise-control button cycles through') \
        .add_argument('cycle', choices=SINGLE_PRESS)
    sub.add_parser('voice-aware', help='voice aware').add_argument('level', choices=['off', *VOICE_AWARE_LEVELS])
    sub.add_parser('smart-av', help='smart audio & video (reconnects)').add_argument('mode', choices=SMART_AV)
    sub.add_parser('autoplay', help='auto play & pause').add_argument('state', choices=ON_OFF)
    p = sub.add_parser('psa', help='personal sound amplification')
    p.add_argument('state', nargs='?', choices=ON_OFF)
    p.add_argument('--balance', type=balance_byte, help='-15 (left) .. 15 (right)')
    p.add_argument('--gain', type=int, choices=range(1, 6), help='1..5')
    sub.add_parser('balance', help='left/right balance: on, off, or -15..15') \
        .add_argument('value')
    sub.add_parser('assistant', help='voice assistant (restarts headphones)') \
        .add_argument('which', choices=ASSISTANT)
    sub.add_parser('prompts', help='voice prompts').add_argument('state', choices=ON_OFF)
    sub.add_parser('volume-limit', help='max volume limiter').add_argument('state', choices=ON_OFF)
    sub.add_parser('auto-off', help='auto power off').add_argument('time', choices=['off', *AUTO_OFF])
    sub.add_parser('battery')
    sub.add_parser('info', help='serial number')
    sub.add_parser('raw', help='send a hex frame and print the replies').add_argument('hex')
    return ap


async def main():
    a = parser().parse_args()
    if a.cmd == 'balance' and a.value not in ('on', 'off'):
        try:
            balance_byte(a.value)
        except (ValueError, argparse.ArgumentTypeError):
            sys.exit('balance: use on, off, or a number from -15 (left) to 15 (right)')
    dev = await BleakScanner.find_device_by_filter(
        lambda d, _: (d.name or '').startswith(NAME_PREFIX), timeout=15)
    if not dev:
        sys.exit('headphones not found: are they on and in range?')
    async with BleakClient(dev) as c:
        j = JBL(c)
        await j.start()
        try:
            await run(a, j)
        except (TimeoutError, RuntimeError) as e:
            sys.exit(f'error: {e}')


if __name__ == '__main__':
    asyncio.run(main())
