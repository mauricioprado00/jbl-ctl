import sys, collections, struct
sys.path.insert(0, __import__('os').path.dirname(__file__))
from btsnoop import records, acl, fmt_t
path = sys.argv[1]
recs = list(records(path))
print('records', len(recs), 'from', fmt_t(recs[0][0]), 'to', fmt_t(recs[-1][0]))
# connection complete events -> handle to bdaddr
for t, d, typ, p in recs:
    if typ == 4 and p[0] == 0x03 and p[2] == 0:  # Connection Complete
        h = struct.unpack('<H', p[3:5])[0]
        addr = ':'.join('%02X' % b for b in reversed(p[5:11]))
        print(fmt_t(t), 'conn complete handle', hex(h), addr)
    if typ == 4 and p[0] == 0x3e and p[2] == 0x01 and p[3] == 0:  # LE conn complete
        h = struct.unpack('<H', p[4:6])[0]
        addr = ':'.join('%02X' % b for b in reversed(p[8:14]))
        print(fmt_t(t), 'LE conn complete handle', hex(h), addr)
c = collections.Counter((h, cid, d) for t, d, h, cid, pl in acl(path))
for k, v in sorted(c.items()):
    print('handle %#x cid %#06x %s %d' % (k[0], k[1], k[2], v))
# L2CAP signaling: connection requests (PSM)
for t, d, h, cid, pl in acl(path):
    if cid == 1:
        i = 0
        while i + 4 <= len(pl):
            code, ident, ln = pl[i], pl[i+1], struct.unpack('<H', pl[i+2:i+4])[0]
            body = pl[i+4:i+4+ln]
            if code == 2:
                psm, scid = struct.unpack('<HH', body[:4]); print(fmt_t(t), d, 'ConnReq psm', hex(psm), 'scid', hex(scid))
            if code == 3:
                dcid, scid, res = struct.unpack('<HHH', body[:6]); print(fmt_t(t), d, 'ConnRsp dcid', hex(dcid), 'scid', hex(scid), 'res', res)
            i += 4 + ln
