import asyncio, sys
from bleak import BleakClient, BleakScanner
NOTIFY = '65786365-6c70-6f69-6e74-2e636f6d0001'
WRITE  = '65786365-6c70-6f69-6e74-2e636f6d0002'
async def main():
    dev = await BleakScanner.find_device_by_filter(lambda d, a: (d.name or '').startswith('JBL Live 770NC'), timeout=15)
    print('found', dev)
    if not dev: return
    async with BleakClient(dev) as c:
        for s in c.services:
            print(s.uuid, [ (ch.uuid, ch.properties) for ch in s.characteristics])
        got = asyncio.Queue()
        await c.start_notify(NOTIFY, lambda _, d: got.put_nowait(bytes(d)))
        for q in sys.argv[1:]:
            await c.write_gatt_char(WRITE, bytes.fromhex(q), response=True)
            try: print(q, '->', (await asyncio.wait_for(got.get(), 3)).hex(' '))
            except asyncio.TimeoutError: print(q, '-> (no reply)')
asyncio.run(main())
