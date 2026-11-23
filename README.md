# jbl-ctl

Control the **JBL Live 770NC** headphones from a Linux terminal: noise
cancelling, EQ, spatial sound and every other setting the JBL Headphones app
offers, over Bluetooth LE, with no phone involved.

```
$ jbl
battery                50%
noise control          anc
eq                     off
low-volume dynamic EQ  off
spatial sound          music
single press           anc-ambient-off
voice aware            off
smart audio & video    audio
personal sound amp     off, balance +0, gain 3
left/right balance     on, +0
voice assistant        native
voice prompts          on (english)
max volume limiter     on
auto power off         off
```

Not affiliated with JBL or Harman. The protocol was worked out from Bluetooth
captures of the official Android app talking to a pair of these headphones.

## Supported model

| | |
|---|---|
| Model | **JBL Live 770NC** (over-ear, adaptive noise cancelling) |
| Bluetooth LE name | `JBL Live 770NC-LE` (the audio device is `JBL Live 770NC`) |
| Control service | `65786365-6c70-6f69-6e74-2e636f6d0000` |
| Tested on | one unit, Ubuntu 24.04, BlueZ 5.72 |

Other JBL models that the same app supports (Live 670NC, Tour, Tune…) may use
the same service and framing, but their command IDs and values are untested.
The tool finds headphones by the name prefix `JBL Live 770NC`; edit
`NAME_PREFIX` in `jbl.py` to try another model, and use `jbl raw` to explore.
Reports for other models are welcome.

## Install

Needs Python 3.12 (older 3.x likely fine), BlueZ, and [bleak](https://github.com/hbldh/bleak).

```sh
git clone https://github.com/mauricioprado00/jbl-ctl.git
cd jbl-ctl
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Put a launcher on your `PATH`, e.g. `/usr/local/bin/jbl`:

```sh
#!/bin/sh
exec /path/to/jbl-ctl/.venv/bin/python /path/to/jbl-ctl/jbl.py "$@"
```

The headphones only need to be on and in range. Pairing over LE isn't
required: the tool scans, connects, sends a command, and disconnects (about
5 seconds per command).

**Close the JBL app on your phone first.** While the app is connected, the
headphones stop answering other clients.

## Commands

| Setting | Command |
|---|---|
| Show everything | `jbl` / `jbl status` |
| Noise control | `jbl anc` · `jbl ambient` · `jbl talkthru` · `jbl off` |
| Equalizer preset | `jbl eq off\|studio\|bass\|club\|extreme-bass\|vocal\|jazz` |
| Low-volume dynamic EQ | `jbl dynamic-eq on\|off` |
| Spatial sound | `jbl spatial off\|music\|movie\|game` |
| Modes the noise-control button cycles through | `jbl single-press anc-ambient\|anc-ambient-off\|ambient-off\|anc-off` |
| Voice Aware | `jbl voice-aware off\|low\|mid\|high` |
| Smart Audio & Video | `jbl smart-av audio\|video\|off` |
| Auto play & pause | `jbl autoplay on\|off` |
| Personal sound amplification | `jbl psa on\|off [--balance -15..15] [--gain 1-5]` |
| Left/right balance | `jbl balance on\|off\|-15..15` |
| Voice assistant | `jbl assistant native\|google\|alexa` |
| Voice prompts | `jbl prompts on\|off` |
| Max volume limiter | `jbl volume-limit on\|off` |
| Auto power off | `jbl auto-off off\|30\|1h\|2h` |
| Battery | `jbl battery` |
| Serial number | `jbl info` |
| Send any frame | `jbl raw aa910111` |

Notes:

- `smart-av` makes the headphones drop and re-establish the LE link, and
  `assistant` restarts them, just as in the app.
- Turning personal sound amplification on switches noise control and spatial
  sound off; the headphones do that themselves.
- `autoplay` is accepted and acknowledged but can't be read back, so `status`
  doesn't show it.
- **Not supported:** changing the voice-prompt language. The app downloads a
  voice pack over an encrypted Bluetooth Classic channel rather than sending a
  setting. `status` still shows the current language.

## Protocol

Everything goes through one GATT service:

| Characteristic | UUID | Use |
|---|---|---|
| Write | `65786365-6c70-6f69-6e74-2e636f6d0002` | commands (write with response) |
| Notify | `65786365-6c70-6f69-6e74-2e636f6d0001` | replies and unsolicited status |

(The UUIDs spell `excelpoint.com` in ASCII.)

Frames are `aa <cmd> <len> <payload…>`. Replies to EQ (`a2`) use a 16-bit
little-endian length. Simple setters are acknowledged with
`aa 00 02 <cmd> 00`. Some requests are answered with `aa ee 02 <cmd> <code>`,
which looks like a status/refusal; the tool treats it as an error.

| Cmd | Request | Reply / meaning |
|---|---|---|
| `91` | `11` get · `10 01 <anc> 02 <ambient> 03 <talkthru>` set · `13` all off | `12` + same TLV |
| `a2` | `01 ff` get · `03 <preset> …` set | `04 <preset> …`; 10 bands of `0a 01 <gain f32> <freq f32>` at 32 Hz…16 kHz |
| `9e` | `01` get · `00 <on>` set | low-volume dynamic EQ |
| `9d` | `01` get · `00 <on> <mode>` set | spatial sound; mode 1 music, 2 movie, 3 game |
| `77` | `01 ff` get · `00 <key> <value>…` set | gestures as TLV; key `06` single press, `0e` assistant |
| `98` | `01` get · `00 <level> <on>` set | Voice Aware; level 1–3 |
| `81`/`82` | `82` get · `81 <8 bytes>` set | Smart Audio & Video, reply `83` |
| `35` | `<on>` | auto play & pause |
| `a0` | `01` get · `00 01 <on> 02 <balance> 03 <gain>` set | personal sound amplification; balance 100 = centre |
| `a8` | `01` get · `00 01 <on> 02 <balance>` set | left/right balance; 100 = centre |
| `34` | `<id>` | voice assistant: `df` native, `01` Google, `02` Alexa |
| `93` | `04` prompts state · `01` language · `03 <on>` set | voice prompts; language `01` English, `0b` Spanish |
| `a5` | `01` get · `00 01 <on>` set | max volume limiter |
| `33` | `<on> <minutes u16>` | auto power off |
| `21` | `30` / `35` | settings block (auto-off at bytes 10–12) / assistant |
| `25` | `00` | status; byte 3 is battery % (also pushed every ~2 s) |
| `94` | `01` | serial number (ASCII) |

### Reverse-engineering your own model

`tools/` holds the scripts used to decode the captures:

1. On Android, enable *Developer options → Enable Bluetooth HCI snoop log*,
   toggle Bluetooth off and on, then change settings in the JBL app one at a
   time with a pause between each.
2. `adb bugreport bugreport.zip` and extract `FS/data/log/bt/btsnoop_hci.log`.
3. `python3 tools/summary.py btsnoop_hci.log` lists connections and channels;
   `python3 tools/frames.py btsnoop_hci.log` prints every app↔headphone frame
   with timestamps to line up against what you tapped.
4. `.venv/bin/python tools/seq.py <hex> <hex>…` sends frames and prints all
   notifications.

Snoop logs and bug reports contain personal data (contacts, accounts, pairing
keys); don't publish them.
