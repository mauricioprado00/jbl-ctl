import sys, os, struct
sys.path.insert(0, os.path.dirname(__file__))
from btsnoop import records, acl, fmt_t
path = sys.argv[1]
trunc = sum(1 for _ in [0])
# truncation check
import struct as s
with open(path,'rb') as f:
    f.read(16); n=tr=0
    while True:
        rh=f.read(24)
        if len(rh)<24: break
        o,i,_,_,_=s.unpack('>IIIIq',rh); f.read(i); n+=1; tr+= (o!=i)
print('truncated records:', tr, 'of', n)
for t, d, h, cid, pl in acl(path):
    if cid in (0x41, 0x3040):  # RFCOMM
        addr, ctrl = pl[0], pl[1]
        dlci = addr >> 2
        l = pl[2] >> 1; off = 3
        if not pl[2] & 1:
            l = (pl[2] >> 1) | (pl[3] << 7); off = 4
        if (ctrl & 0xef) == 0xef and dlci and (ctrl & 0x10) and len(pl) > off + l:
            credits = pl[off]; off += 1  # credit-based flow
        data = pl[off:off+l]
        print(fmt_t(t), d, 'RFCOMM dlci', dlci, 'ctrl %02x' % ctrl, data.hex(' '))
    elif cid == 4:
        print(fmt_t(t), d, 'ATT', pl.hex(' '))
