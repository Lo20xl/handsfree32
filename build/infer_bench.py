"""Inference benchmark: mediapipe hand landmarker ms/frame at several sizes + GPU delegate probe.
Run from repo root: .venv/Scripts/python.exe build/infer_bench.py
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

# --- GPU delegate availability probe ---
try:
    from mediapipe.tasks.python.core.base_options import Delegate as _D  # noqa
    print("Delegate enum:", [a for a in dir(_D) if not a.startswith("_")])
except Exception as e:
    print("Delegate enum import failed:", e)
    _D = None

if _D is not None:
    for name in ("GPU", "CPU"):
        val = getattr(_D, name, None)
        if val is None:
            print(f"delegate {name}: not present")
            continue
        try:
            opts = vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=MODEL, delegate=val),
                running_mode=vision.RunningMode.VIDEO, num_hands=3)
            lm = vision.HandLandmarker.create_from_options(opts)
            img = MpImage(image_format=ImageFormat.SRGB,
                          data=np.zeros((480, 854, 3), dtype=np.uint8))
            t0 = time.perf_counter()
            lm.detect_for_video(img, 1)
            print(f"delegate {name}: created + ran OK, first infer {(time.perf_counter()-t0)*1000:.1f} ms")
            lm.close()
        except Exception as e:
            print(f"delegate {name}: FAILED -> {e!r}")

# --- CPU timing at several input sizes ---
opts = vision.HandLandmarkerOptions(
    base_options=mp_python.BaseOptions(model_asset_path=MODEL),
    running_mode=vision.RunningMode.VIDEO, num_hands=3)
lm = vision.HandLandmarker.create_from_options(opts)
for (h, w) in ((480, 854), (480, 640), (720, 1280), (1080, 1920)):
    img = MpImage(image_format=ImageFormat.SRGB,
                  data=(np.random.rand(h, w, 3) * 255).astype(np.uint8))
    for i in range(5):
        lm.detect_for_video(img, 30 + i)
    ts = []
    for i in range(30):
        t0 = time.perf_counter()
        lm.detect_for_video(img, 100 + i)
        ts.append((time.perf_counter() - t0) * 1000)
    ts.sort()
    print(f"CPU {w}x{h}: p50 {ts[len(ts)//2]:.1f} ms  p95 {ts[int(len(ts)*.95)]:.1f} ms")
lm.close()
print("INFER_BENCH_DONE")
