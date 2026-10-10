"""Inference benchmark v2: mediapipe CPU ms/frame at several sizes + GPU delegate probe.
Run from repo root: .venv/Scripts/python.exe build/infer_bench2.py
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mediapipe import Image as MpImage, ImageFormat
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from handjob.paths import assets_dir

MODEL = os.path.join(assets_dir(), "hand_landmarker.task")

# --- GPU delegate probe ---
D = getattr(mp_python.BaseOptions, "Delegate", None)
print("BaseOptions.Delegate:", D, "| members:", [a for a in dir(D) if not a.startswith("_")] if D else None)
if D is not None:
    for name in ("GPU", "CPU"):
        val = getattr(D, name, None)
        if val is None:
            print(f"delegate {name}: not present")
            continue
        try:
            opts = vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=MODEL, delegate=val),
                running_mode=vision.RunningMode.VIDEO, num_hands=3)
            lm = vision.HandLandmarker.create_from_options(opts)
            img = MpImage(image_format=ImageFormat.SRGB, data=np.zeros((480, 854, 3), dtype=np.uint8))
            t0 = time.perf_counter()
            lm.detect_for_video(img, 1)
            print(f"delegate {name}: OK, first infer {(time.perf_counter()-t0)*1000:.1f} ms")
            lm.close()
        except Exception as e:
            print(f"delegate {name}: FAILED -> {e!r}")

# --- CPU timing at several input sizes (monotonic timestamps globally) ---
opts = vision.HandLandmarkerOptions(
    base_options=mp_python.BaseOptions(model_asset_path=MODEL),
    running_mode=vision.RunningMode.VIDEO, num_hands=3)
lm = vision.HandLandmarker.create_from_options(opts)
ts_ms = 1
for (h, w) in ((360, 640), (480, 854), (720, 1280), (1080, 1920)):
    img = MpImage(image_format=ImageFormat.SRGB,
                  data=(np.random.rand(h, w, 3) * 255).astype(np.uint8))
    for _ in range(5):
        ts_ms += 33
        lm.detect_for_video(img, ts_ms)
    ts = []
    for _ in range(30):
        t0 = time.perf_counter()
        ts_ms += 33
        lm.detect_for_video(img, ts_ms)
        ts.append((time.perf_counter() - t0) * 1000)
    ts.sort()
    print(f"CPU {w}x{h}: p50 {ts[len(ts)//2]:.1f} ms  p95 {ts[int(len(ts)*.95)]:.1f} ms")
lm.close()

# --- resize cost probe ---
import cv2  # noqa: E402
big = (np.random.rand(720, 1280, 3) * 255).astype(np.uint8)
for (h, w) in ((480, 854), (360, 640), (720, 1280)):
    t0 = time.perf_counter()
    for _ in range(50):
        cv2.resize(big, (w, h), interpolation=cv2.INTER_AREA)
    print(f"resize 1280x720 -> {w}x{h}: {(time.perf_counter()-t0)*1000/50:.2f} ms/call")
t0 = time.perf_counter()
for _ in range(50):
    small = cv2.resize(big, (854, 480), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(cv2.flip(small, 1), cv2.COLOR_BGR2RGB)
print(f"resize+flip+cvt on 854x480: {(time.perf_counter()-t0)*1000/50:.2f} ms/call")
print("INFER_BENCH2_DONE")
