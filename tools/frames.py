"""Print JBL app<->headphone frames (ATT write to 0x39 / notify on 0x35) from a btsnoop log."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from btsnoop import acl, fmt_t
for t, d, h, cid, pl in acl(sys.argv[1]):
    if cid != 4 or len(pl) < 3:
        continue
    op, handle = pl[0], pl[1] | pl[2] << 8
    if op in (0x12, 0x52) and handle == 0x39:
        print(fmt_t(t), 'APP', pl[3:].hex(' '))
    elif op == 0x1b and handle == 0x35:
        print(fmt_t(t), ' HP', pl[3:].hex(' '))
