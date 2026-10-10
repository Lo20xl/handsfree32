"""Overlay capture test — Windows.Graphics.Capture (DWM compositor path).

Captures the primary monitor via WindowsCapture (sees layered windows), arms
the overlay orb at (700,500), grabs the latest frame, pixel-checks for the orb.
"""
import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT = os.path.dirname(os.path.abspath(__file__))

def log(msg):
    print(msg, flush=True)

import numpy as np
from windows_capture import WindowsCapture

from handjob.engine import CursorBus
from handjob.overlay import Overlay

latest = {"frame": None, "shape": None, "err": None}
frames_seen = {"n": 0}

cap = WindowsCapture(cursor_capture=True, monitor_index=1)  # 1-based

@cap.event
def on_frame_arrived(frame, control):
    frames_seen["n"] += 1
    try:
        arr = np.array(frame.frame_buffer)
        latest["frame"] = arr
        latest["shape"] = arr.shape
    except Exception as e:
        latest["err"] = repr(e)
        try:
            latest["frame"] = frame.convert_to_bgra()
            latest["shape"] = getattr(latest["frame"], "shape", "?")
        except Exception as e2:
            latest["err"] = f"{e!r} / {e2!r}"

@cap.event
def on_closed():
    log("capture closed")

cap.start_free_threaded()
time.sleep(2.0)
log(f"capture frames seen: {frames_seen['n']}, shape={latest['shape']}, err={latest['err']}")

# baseline pixel before the orb
if latest["frame"] is not None:
    f = latest["frame"]
    log(f"baseline px @700,500: {tuple(int(v) for v in f[500, 700][:4]) if f.ndim == 3 else 'ndim?'}")

# now arm the overlay
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

time.sleep(2.0)
log(f"overlay: error={bus.error!r} visible={ov._visible}")

if latest["frame"] is not None:
    f = latest["frame"]
    log(f"armed px @700,500: {tuple(int(v) for v in f[500, 700][:4])}")
    log(f"armed px @700,490: {tuple(int(v) for v in f[490, 700][:4])}")
    # sky pixel count in 100x100 box
    h, w = f.shape[:2]
    box = f[450:550, 650:750]
    r = box[:, :, 2].astype(int); g = box[:, :, 1].astype(int); b = box[:, :, 0].astype(int)
    sky = int(((b > 180) & (g > 120) & (g < 230) & (r < 140)).sum())
    log(f"SKY_PIXELS in 100x100 box: {sky} / 10000")
    # save the crop + full frame
    try:
        from PIL import Image
        Image.fromarray(f[:, :, :3][:, :, ::-1]).save(os.path.join(OUT, "wgc_full.png"))
        Image.fromarray(f[400:600, 600:800, :3][:, :, ::-1]).save(os.path.join(OUT, "wgc_crop.png"))
        log("saved wgc_full.png + wgc_crop.png")
    except Exception as e:
        log(f"save failed: {e!r}")

with bus.lock:
    bus.armed = False
time.sleep(0.3)
ov.stop()
try:
    cap.stop()
except Exception:
    pass
log("DONE")
