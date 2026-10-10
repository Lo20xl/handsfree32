"""Can MediaPipe's Windows Python build run the HandLandmarker on the GPU?

Tries the GPU delegate (and Edge/OpenGL if present), reports what the current
installed mediapipe supports. Run from repo root:
  .venv/Scripts/python.exe build/gpu_delegate_check.py
"""
import time

import mediapipe as mp

print("mediapipe", mp.__version__)

from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python import vision

MODEL = "handjob/assets/hand_landmarker.task"


def try_delegate(name):
    try:
        delegate = getattr(BaseOptions.Delegate, name)
    except AttributeError:
        print(f"{name:6s}: not present in this build")
        return
    try:
        opts = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=MODEL, delegate=delegate),
            num_hands=1)
        lm = vision.HandLandmarker.create_from_options(opts)
        import numpy as np
        from mediapipe import Image, ImageFormat
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        t0 = time.perf_counter()
        for i in range(5):
            lm.detect_for_video(Image(image_format=ImageFormat.SRGB, data=img), int(t0 * 1000) + i * 33)
        dt = (time.perf_counter() - t0) / 5 * 1000
        print(f"{name:6s}: OK — {dt:.1f} ms/frame")
        lm.close()
    except Exception as e:
        print(f"{name:6s}: FAIL — {type(e).__name__}: {str(e)[:180]}")


for d in ("GPU", "CPU"):
    try_delegate(d)
