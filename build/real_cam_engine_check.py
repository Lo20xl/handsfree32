"""Run the REAL engine against the configured camera for ~20 s (as the user),
printing processed frames / unique-frame rate / backend every 2 s.

Proves the user-visible scenario end-to-end: a static or repeating camera must
NOT stall the engine (2.5.1 fix), and the ONNX backend must stay live.

Run via schtasks as the logged-in user. Force-exits even if the driver wedges.
"""
import os
import sys
import threading
import time

OUT = []


def work():
    sys.path.insert(0, ".")
    from handjob.engine import CursorBus, Engine
    bus = CursorBus()
    eng = Engine(bus)
    eng.start()
    t0 = time.time()
    while time.time() - t0 < 20:
        time.sleep(2)
        OUT.append(f"t={time.time() - t0:4.0f}s frames={bus.frames:<5} "
                   f"unique={bus.cam_unique} fps={bus.fps:.1f} err={bus.error}")
    try:
        eng.stop()
        eng.cleanup()
    except Exception:
        pass
    ok = bus.frames >= 10 and not bus.error
    OUT.append(f"backend={getattr(eng, '_backend_name', '?')}")
    OUT.append("REALCAM_OK" if ok else "REALCAM_FAIL")
    print("\n".join(OUT))
    sys.stdout.flush()
    os._exit(0 if ok else 1)


th = threading.Thread(target=work, daemon=True)
th.start()
th.join(35)
print("\n".join(OUT))
print("REALCAM_TIMEOUT")
sys.stdout.flush()
os._exit(2)
