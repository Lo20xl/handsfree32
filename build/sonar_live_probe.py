"""Live hardware probe for the sonar stack — NO sound is emitted.
Verifies: (a) the laptop mic opens and delivers blocks (MME host API),
(b) an output stream at the tone frequency configures on the laptop speakers,
(c) analyze() runs on real ambient audio without crashing.

Run: .venv/Scripts/python.exe build/sonar_live_probe.py
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sounddevice as sd  # noqa: E402

from handjob.sonar import BLOCK, analyze  # noqa: E402

print("sounddevice", sd.__version__)
apis = {i: str(a.get("name")) for i, a in enumerate(sd.query_hostapis())}
print("hostapis:", apis)


def find(name_part, kind):
    """First matching device that is NOT on a WDM-KS host API."""
    for i, d in enumerate(sd.query_devices()):
        name = str(d.get("name", ""))
        if name_part.lower() not in name.lower():
            continue
        if "wdm-ks" in apis.get(int(d.get("hostapi", -1)), "").lower():
            continue
        if kind == "in" and d.get("max_input_channels", 0) > 0:
            return i, d
        if kind == "out" and d.get("max_output_channels", 0) > 0:
            return i, d
    return None, None


IN, din = find("Realtek HD Audio Mic", "in")
OUT, dout = find("Realtek HD Audio output", "out")
print(f"realtek mic: idx {IN} ({din and din.get('name')}) | speakers: idx {OUT} ({dout and dout.get('name')})")

# --- (a) open the mic for 2 s, run analyze() on the real blocks -------------
sr = int(din.get("default_samplerate") or 44100)
print(f"mic rate {sr} Hz (Nyquist {sr/2:.0f} Hz)")
got = []
with sd.InputStream(samplerate=sr, channels=1, dtype="float32", blocksize=BLOCK, device=IN) as stream:
    t0 = time.time()
    while time.time() - t0 < 2.0:
        data, overflow = stream.read(BLOCK)
        got.append(data[:, 0].copy())
print(f"mic blocks: {len(got)} in 2 s ({BLOCK} frames each)")

state = {}
for i, block in enumerate(got[-5:]):
    d = analyze(block, sr, 19000.0, state)
    print(f"  block {i}: carrier +{d['carrier_db']:.1f} dB vs floor {d['floor_db']:.1f} | "
          f"score {d['score']:.2f} dir {d['direction']:+d}")
peak = max(float(np.max(np.abs(b))) for b in got)
print(f"ambient peak amplitude: {peak:.4f}")

# --- (b) speakers: can they host a 19 kHz output stream? (nothing played) ---
osr = int(dout.get("default_samplerate") or 48000)
ok_msg = "config OK (stream created + closed, no sound emitted)"
try:
    s = sd.OutputStream(samplerate=osr, channels=1, dtype="float32", blocksize=BLOCK, device=OUT)
    s.close()
except Exception as e:
    ok_msg = f"FAILED: {e!r}"
print(f"speakers rate {osr} Hz -> tone stream {ok_msg}")
print(f"tone check: 19000 Hz needs < {osr/2:.0f} Hz Nyquist -> "
      f"{'OK' if 19000 < osr/2 else 'NOT SUPPORTED'}, 21000 Hz -> {'OK' if 21000 < osr/2 else 'NOT SUPPORTED'}")
print("SONAR_PROBE_DONE")
