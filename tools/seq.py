"""Send several hex frames in one connection and print every notification."""
import asyncio, sys
from bleak import BleakClient, BleakScanner
NOTIFY = '65786365-6c70-6f69-6e74-2e636f6d0001'; WRITE = '65786365-6c70-6f69-6e74-2e636f6d0002'
async def main():
    dev = await BleakScanner.find_device_by_filter(lambda d, _: (d.name or '').startswith('JBL Live 770NC'), timeout=15)
    async with BleakClient(dev) as c:
        await c.start_notify(NOTIFY, lambda _, d: print('   <-', bytes(d).hex(' ')))
        await asyncio.sleep(1)
        for h in sys.argv[1:]:
            print('->', h); await c.write_gatt_char(WRITE, bytes.fromhex(h), response=True); await asyncio.sleep(0.8)
asyncio.run(main())
