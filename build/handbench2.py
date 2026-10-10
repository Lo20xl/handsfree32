"""num_hands cost with REAL hands in frame — the decide-60Hz benchmark.
Run: .venv/Scripts/python.exe build/handbench2.py
"""
import os
import sys
import time

import cv2
from mediapipe import Image as MpImage, ImageFormat
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from handjob.paths import assets_dir  # noqa: E402
from handjob.engine import MODEL_NAME  # noqa: E402

MODEL = os.path.join(assets_dir(), MODEL_NAME)
img = cv2.imread(os.path.join(assets_dir(), "sample_hands.jpg"))
base = cv2.resize(img, (854, 480), interpolation=cv2.INTER_AREA)
rgb = cv2.cvtColor(cv2.flip(base, 1), cv2.COLOR_BGR2RGB)

for nh in (1, 2, 3):
    lm = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=MODEL),
        running_mode=vision.RunningMode.VIDEO, num_hands=nh))
    ts = 1
    for _ in range(8):
        ts += 16
        lm.detect_for_video(MpImage(image_format=ImageFormat.SRGB, data=rgb), ts)
    out = []
    nhands = 0
    for _ in range(60):
        t0 = time.perf_counter()
        ts += 16
        res = lm.detect_for_video(MpImage(image_format=ImageFormat.SRGB, data=rgb), ts)
        out.append((time.perf_counter() - t0) * 1000)
        nhands = len(res.hand_landmarks)
    out.sort()
    print(f"num_hands={nh}: p50 {out[len(out)//2]:.2f} ms  p95 {out[int(len(out)*.95)]:.2f}  max {out[-1]:.2f} (detected {nhands})")
    lm.close()

# full pipeline capacity at num_hands=1: capture-size resize + flip+cvt + infer + 30fps jpeg
lm = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
    base_options=mp_python.BaseOptions(model_asset_path=MODEL),
    running_mode=vision.RunningMode.VIDEO, num_hands=1))
N, ts = 150, 1
t0 = time.perf_counter()
for i in range(N):
    small = cv2.resize(img, (854, 480), interpolation=cv2.INTER_AREA)  # simulates engine resize
    rgb = cv2.cvtColor(cv2.flip(small, 1), cv2.COLOR_BGR2RGB)
    ts += 16
    lm.detect_for_video(MpImage(image_format=ImageFormat.SRGB, data=rgb), ts)
    if i % 2 == 0:
        cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 55])
dt = time.perf_counter() - t0
print(f"pipeline num_hands=1 (resize+cvt+infer+30fps jpeg): {N} in {dt:.2f}s = {N/dt:.1f} fps capacity")
lm.close()
print("HANDBENCH2_DONE")
