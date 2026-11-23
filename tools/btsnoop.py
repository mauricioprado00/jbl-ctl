"""Minimal btsnoop (H4) parser: yields (ts_seconds, direction, hci_type, payload)."""
import struct, sys, datetime

EPOCH_DELTA = 0x00dcddb30f2f8000  # µs between 0000-01-01 and 1970-01-01

def records(path):
    with open(path, 'rb') as f:
        hdr = f.read(16)
        assert hdr[:8] == b'btsnoop\0', 'not btsnoop'
        while True:
            rh = f.read(24)
            if len(rh) < 24:
                return
            olen, ilen, flags, drops, ts = struct.unpack('>IIIIq', rh)
            data = f.read(ilen)
            sent = not (flags & 1)  # bit0: 0 = host->controller (sent)
            t = (ts - EPOCH_DELTA) / 1e6
            yield t, ('>' if sent else '<'), data[0], data[1:]

def acl(path):
    """Reassemble L2CAP frames: yields (t, dir, handle, cid, payload)."""
    partial = {}
    for t, d, typ, p in records(path):
        if typ != 2 or len(p) < 4:
            continue
        h, ln = struct.unpack('<HH', p[:4])
        handle, pb = h & 0x0fff, (h >> 12) & 3
        body = p[4:4 + ln]
        key = (handle, d)
        if pb in (0, 2):  # start
            partial[key] = [t, bytearray(body)]
        elif key in partial:
            partial[key][1] += body
        else:
            continue
        t0, buf = partial[key]
        if len(buf) >= 4:
            l2len, cid = struct.unpack('<HH', buf[:4])
            if len(buf) >= 4 + l2len:
                yield t0, d, handle, cid, bytes(buf[4:4 + l2len])
                del partial[key]

def fmt_t(t):
    return datetime.datetime.fromtimestamp(t).strftime('%H:%M:%S.%f')[:-3]
