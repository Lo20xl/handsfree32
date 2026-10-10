"""Realistic inference cost: sample image WITH HANDS (full palm+landmark stages), as
it would run in the 60 Hz loop. Run: .venv/Scripts/python.exe build/handbench.py
"""
import os
import sys
import time

import cv2
import numpy as np
from mediapipe import Image as MpImage, ImageFormat
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from handjob.paths import assets_dir  # noqa: E402
from handjob.engine import MODEL_NAME  # noqa: E402

MODEL = os.path.join(assets_dir(), MODEL_NAME)
img_path = os.path.join(assets_dir(), "sample_hands.jpg")
img = cv2.imread(img_path)
print("sample:", img_path, img.shape)

lm = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
    base_options=mp_python.BaseOptions(model_asset_path=MODEL),
    running_mode=vision.RunningMode.VIDEO, num_hands=3))

# feed the real image repeatedly at 854x480 and 1280x720
for (h, w) in ((480, 854), (720, 1280)):
    fr = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(cv2.flip(fr, 1), cv2.COLOR_BGR2RGB)
    ts = 1
    for _ in range(6):
        ts += 16
        lm.detect_for_video(MpImage(image_format=ImageFormat.SRGB, data=rgb), ts)
    out = []
    nhands = 0
    for _ in range(50):
        t0 = time.perf_counter()
        ts += 16
        res = lm.detect_for_video(MpImage(image_format=ImageFormat.SRGB, data=rgb), ts)
        out.append((time.perf_counter() - t0) * 1000)
        nhands = len(res.hand_landmarks)
    out.sort()
    print(f"infer WITH hands {w}x{h}: p50 {out[len(out)//2]:.2f} ms  p95 {out[int(len(out)*.95)]:.2f}  "
          f"max {out[-1]:.2f}  (hands detected: {nhands})")
lm.close()

# full 60 Hz pipeline dry-run with hands present
lm = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
    base_options=mp_python.BaseOptions(model_asset_path=MODEL),
    running_mode=vision.RunningMode.VIDEO, num_hands=3))
t0 = time.perf_counter()
N = 120
ts = 1
for i in range(N):
    fr = img if (i % 2) else cv2.resize(img, (854, 480), interpolation=cv2.INTER_AREA)
    small = cv2.resize(fr, (854, 480), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(cv2.flip(small, 1), cv2.COLOR_BGR2RGB)
    ts += 16
    lm.detect_for_video(MpImage(image_format=ImageFormat.SRGB, data=rgb), ts)
    if i % 2 == 0:  # ~30 fps preview encode
        cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 55])
dt = time.perf_counter() - t0
print(f"pipeline dry-run: {N} iters in {dt:.2f}s = {N/dt:.1f} fps capacity (resize+flipcvt+infer+30fps jpeg, hands present)")
lm.close()
print("HANDBENCH_DONE")
