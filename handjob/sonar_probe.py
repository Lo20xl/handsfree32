"""Tone sweep for the sonar channel: which carrier can this machine's
speaker->mic path actually carry?

The app's default is 19 kHz, but the INPUT device's sample rate sets the usable
band: at 44.1 kHz Nyquist is 22.05 kHz, so 19 kHz sits at 86% of it — inside the
anti-alias filter's rolloff and above most laptop mics' response. A tone the mic
cannot hear produces a carrier only a couple of dB over the noise floor, which
reads as "the sonar is dead" when the streams are in fact fine.

Runs each tone for a few seconds, reports the carrier-over-floor level, and
picks the highest tone that is still clearly audible to the mic.
"""
from __future__ import annotations

import sys
import time

from .sonar import Sonar, BLOCK

TONES = (17000, 18000, 19000, 20000, 21000)
SETTLE_S = 2.5


def sweep(tones=TONES):
    print("sonar tone sweep (speaker -> mic path)")
    results = []
    for tone in tones:
        s = Sonar(tone=tone)
        try:
            s.start()
        except Exception as e:
            print(f"  {tone:6d} Hz  START FAILED: {e}")
            results.append((tone, None, None))
            continue
        try:
            t0 = time.time()
            while time.time() - t0 < SETTLE_S and s.diag.get("blocks", 0) < 12:
                time.sleep(0.1)
            d = dict(s.diag)
            carrier = d.get("carrier_db", 0.0)
            print(f"  {tone:6d} Hz  sr={d.get('sr')}  carrier +{carrier:5.1f} dB over floor"
                  f"  blocks={d.get('blocks')}")
            results.append((tone, carrier, d.get("sr")))
        finally:
            s.stop()
            time.sleep(0.3)
    usable = [t for t, c, _ in results if c is not None and c >= 12.0]
    print()
    if usable:
        best = max(usable)
        print(f"SWEEP OK — highest clearly-audible tone: {best} Hz "
              f"(usable: {', '.join(str(t) for t in usable)})")
        print(f"SWEEP_BEST={best}")
    else:
        heard = [(t, round(c, 1)) for t, c, _ in results if c is not None]
        print(f"SWEEP WEAK — no tone reached +12 dB over the floor: {heard}")
        print("  -> the speaker/mic pair cannot carry an ultrasonic tone here;")
        print("     the sonar channel is unavailable on this hardware (not a bug).")
        print("SWEEP_BEST=0")
    return 0


if __name__ == "__main__":
    sys.exit(sweep())
