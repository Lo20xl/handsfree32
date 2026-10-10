"""A/B probe: which camera-open settings (if any) put Camo into its 1 fps state?

Runs four consecutive variants against camera 0, each with a short settle,
reporting reads/s, unique rate and brightness per variant:
  A plain:   no CAP_PROP sets (backends default)
  B mjpg:    FOURCC=MJPG only
  C mjpg+sz: FOURCC=MJPG + WIDTH/HEIGHT 640x480
  D mjpg+all: FOURCC=MJPG + 640x480 + FPS 60 + BUFFERSIZE 1  (the app's exact open)
  E plain again (did churn/time itself break it?)
Run directly (no schtasks): .venv/Scripts/python.exe build/cam_ab_probe.py
"""
import sys
import time

import cv2
import numpy as np


def variant(name, apply_fn, secs=2.5):
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"{name}: OPEN FAILED")
        return
    try:
        if apply_fn:
            apply_fn(cap)
    except Exception as e:
        print(f"{name}: set failed: {e}")
    # settle
    time.sleep(0.6)
    t0 = time.time()
    frames = []
    while time.time() - t0 < secs:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    span = max(1e-6, time.time() - t0)

    def sig(f):
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        s = cv2.resize(g, (16, 16), interpolation=cv2.INTER_AREA).astype(np.int16)
        return s - int(s.mean())

    uniq = exact = 0
    prev = None
    for f in frames:
        s = sig(f)
        if prev is not None:
            d = float(np.abs(s - prev).mean())
            if d > 0.35:
                uniq += 1
            if d == 0.0:
                exact += 1
        prev = s
    if frames:
        b = float(frames[-1].mean())
        print(f"{name}: {len(frames)} frames in {span:.1f}s = {len(frames)/span:.1f} reads/s, "
              f"unique={uniq}, exact={exact}, brightness={b:.1f}, size={frames[-1].shape[1]}x{frames[-1].shape[0]}")
    else:
        print(f"{name}: no frames")
    cap.release()
    time.sleep(1.2)


variant("A plain      ", None)
variant("B mjpg       ", lambda c: c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")))
variant("C mjpg+sz    ", lambda c: (c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")),
                                  c.set(cv2.CAP_PROP_FRAME_WIDTH, 640),
                                  c.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)))
variant("D app exact  ", lambda c: (c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")),
                                    c.set(cv2.CAP_PROP_FRAME_WIDTH, 640),
                                    c.set(cv2.CAP_PROP_FRAME_HEIGHT, 480),
                                    c.set(cv2.CAP_PROP_FPS, 60),
                                    c.set(cv2.CAP_PROP_BUFFERSIZE, 1)))
variant("E plain again", None)
print("CAM_AB_DONE")
sys.stdout.flush()
