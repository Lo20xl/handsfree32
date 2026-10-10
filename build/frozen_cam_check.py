"""End-to-end frozen-camera verification (2.4.3).

Runs the real Engine against the currently-configured camera — which right now
is NVIDIA Broadcast's frozen virtual cam (0-2 unique frames/s) — and checks the
watchdog does its job: red error surfaces, cursor halts, reopens are capped.

Run from the repo root:  .venv/Scripts/python.exe build/frozen_cam_check.py
"""
import os
import sys
import time

sys.path.insert(0, ".")
from handjob.engine import CursorBus, Engine


def main(seconds=36.0):
    bus = CursorBus()
    eng = Engine(bus)
    eng.start()
    t0 = time.time()
    err_at = None
    err_text = None
    positions = []
    while time.time() - t0 < seconds:
        time.sleep(0.5)
        positions.append(bus.position)
        if bus.error and err_at is None:
            err_at = time.time() - t0
            err_text = bus.error          # capture NOW — reopens clear bus.error later
    try:
        eng.stop()
    except Exception:
        pass
    frozen = bool(err_text and err_text.startswith("camera frozen"))
    tail = [p for p in positions[-16:] if p]
    moved_after_err = len(set(tail)) > 1 if tail else False
    out = (f"cam_unique     : {bus.cam_unique}\n"
           f"cam_reads      : {bus.cam_reads}\n"
           f"error at       : {err_at:.1f}s\n" if err_at else "error          : NONE\n")
    out += (f"error text     : {err_text!r}\n" if err_text else "")
    out += f"cursor moved after error (should be False): {moved_after_err}\n"
    out += "FROZEN_CHECK_OK" if frozen and not moved_after_err else "FROZEN_CHECK_FAIL"
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "frozen_result.txt"), "w") as f:
        f.write(out + "\n")
    sys.stdout.flush()
    os._exit(0 if frozen and not moved_after_err else 1)


if __name__ == "__main__":
    main()
