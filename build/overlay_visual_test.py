"""Visual overlay test: arm the bus, show the orb, screenshot the desktop.

Run as the logged-in user (session 1) — screenshots + overlay need a desktop.
Outputs: build/overlay_visual_shot.png + build/overlay_visual_out.txt
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)))

def log(msg):
    # stdout is redirected to overlay_visual_out.txt by the .cmd launcher;
    # do NOT reopen that file here (Windows sharing violation with cmd's handle)
    print(msg, flush=True)

from handjob.engine import CursorBus
from handjob.overlay import Overlay

bus = CursorBus()
ov = Overlay(bus, fps=60)
ov.start()
time.sleep(1.2)

if bus.error:
    log(f"ERROR after overlay start: {bus.error}")
    sys.exit(1)

log(f"virtual_screen: {bus.virtual_screen}")

# arm + place the orb at a known spot (screen center-ish)
with bus.lock:
    bus.armed = True
    bus.found = True
    bus.dim = False
    bus.position = (700.0, 500.0)
    bus.style = "sky"
    bus.press = 0.0

time.sleep(1.5)  # let the overlay render several frames

# screenshot the whole virtual screen
try:
    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=True)
    shot = os.path.join(OUT, "overlay_visual_shot.png")
    img.save(shot)
    log(f"SHOT {img.size} -> {shot}")
except Exception as e:
    log(f"SHOT FAILED: {e!r}")

# pixel check around (700,500): is the orb there?
try:
    px = img.load()
    cx, cy = 700, 500
    samples = []
    for dx, dy in ((0, 0), (0, -12), (12, 0), (-12, 0), (0, 12), (20, 20)):
        samples.append(px[cx + dx, cy + dy])
    log(f"PIXELS around orb: {samples}")
    # count sky-ish pixels in a 90px box around the position
    sky = 0
    for yy in range(cy - 45, cy + 45, 3):
        for xx in range(cx - 45, cx + 45, 3):
            r, g, b = px[xx, yy][:3]
            if b > 180 and 120 < g < 230 and r < 140:
                sky += 1
    log(f"SKY_PIXELS in 90x90 box (sampled): {sky}")
except Exception as e:
    log(f"PIXEL CHECK FAILED: {e!r}")

with bus.lock:
    bus.armed = False
time.sleep(0.5)
ov.stop()
log("DONE")
