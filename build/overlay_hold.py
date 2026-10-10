"""Hold the overlay orb on screen for 45s so an external capture can see it.

Orb at (700,500), sky style, armed. Writes a heartbeat to build/overlay_hold_state.txt.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(OUT, "overlay_hold_state.txt")

def log(msg):
    print(msg, flush=True)
    try:
        with open(STATE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

open(STATE, "w").close()
log(f"START {time.strftime('%H:%M:%S')}")

from handjob.engine import CursorBus
from handjob.overlay import Overlay

bus = CursorBus()
ov = Overlay(bus, fps=60)
ov.start()
time.sleep(1.0)

with bus.lock:
    bus.armed = True
    bus.found = True
    bus.dim = False
    bus.position = (700.0, 500.0)
    bus.style = "sky"

log(f"ARMED error={bus.error!r} visible={ov._visible}")

for i in range(45):
    time.sleep(1.0)
    if i % 5 == 4:
        log(f"t={i+1}s error={bus.error!r} visible={ov._visible} loop_errors={getattr(ov,'_loop_errors',0)}")

with bus.lock:
    bus.armed = False
time.sleep(0.5)
ov.stop()
log("DONE")
