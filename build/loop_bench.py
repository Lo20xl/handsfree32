"""Loop bench: where do the ms go in the real engine loop, and can it hold 60 Hz sampling?
Run from repo root: .venv/Scripts/python.exe build/loop_bench.py [cam_index]
"""
import os
import statistics
import sys
import time

import cv2
import numpy as np
from mediapipe import Image as MpImage, ImageFormat
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from handjob.paths import assets_dir  # noqa: E402

CAM = int(sys.argv[1]) if len(sys.argv) > 1 else 0
MODEL = os.path.join(assets_dir(), "hand_landmarker.task")

cap = cv2.VideoCapture(CAM, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
cap.set(cv2.CAP_PROP_FPS, 60)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
ok, f0 = cap.read()
print(f"cam {CAM}: first frame {ok} {None if f0 is None else f0.shape}")

lm = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
    base_options=mp_python.BaseOptions(model_asset_path=MODEL),
    running_mode=vision.RunningMode.VIDEO, num_hands=3))

N = 240
t_read, t_resize, t_flipcvt, t_infer, t_jpeg, t_total = [], [], [], [], [], []
ts_ms = 1
wall0 = time.perf_counter()
for i in range(N):
    ta = time.perf_counter()
    ok, frame = cap.read()
    tb = time.perf_counter()
    if not ok:
        continue
    small = cv2.resize(frame, (854, 480), interpolation=cv2.INTER_AREA)
    tc = time.perf_counter()
    rgb = cv2.cvtColor(cv2.flip(small, 1), cv2.COLOR_BGR2RGB)
    td = time.perf_counter()
    ts_ms += 16
    res = lm.detect_for_video(MpImage(image_format=ImageFormat.SRGB, data=rgb), ts_ms)
    te = time.perf_counter()
    ok_j, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 55])
    tf = time.perf_counter()
    t_read.append((tb - ta) * 1000)
    t_resize.append((tc - tb) * 1000)
    t_flipcvt.append((td - tc) * 1000)
    t_infer.append((te - td) * 1000)
    t_jpeg.append((tf - te) * 1000)
    t_total.append((tf - ta) * 1000)
dt_wall = time.perf_counter() - wall0
print(f"wall: {N} frames in {dt_wall:.1f}s = {N / dt_wall:.1f} fps (read blocks; incl. camera pacing)")


def p(name, xs):
    xs = sorted(xs)
    print(f"  {name:26s} p50 {xs[len(xs)//2]:6.2f} ms  p95 {xs[int(len(xs)*.95)]:6.2f}  max {xs[-1]:6.2f}")


print("per-stage ms:")
p("read() [blocks]", t_read)
p("resize 1280->854", t_resize)
p("flip+cvt", t_flipcvt)
p("mediapipe infer", t_infer)
p("jpeg q55 1280x720", t_jpeg)
p("TOTAL compute (no read)", [a + b + c + d for a, b, c, d in zip(t_resize, t_flipcvt, t_infer, t_jpeg)])
print(f"compute p50 sum: {statistics.median(t_resize) + statistics.median(t_flipcvt) + statistics.median(t_infer):.2f} ms (resize+flip+cvt+infer, no jpeg)")
lm.close()
cap.release()
print("LOOP_BENCH_DONE")
