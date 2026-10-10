"""E2E check: ONNX (DirectML) hand pipeline vs MediaPipe on the same image.

Prints per-landmark deviation (px) and writes a visual overlay PNG
(mediapipe = green, onnx = magenta). Iterate until close, then the ONNX
backend can be wired into the app.

Run: .venv/Scripts/python.exe build/onnx_e2e_probe.py [image]
"""
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, ".")
from handjob.hand_onnx import OnnxHandLandmarker

IMG = sys.argv[1] if len(sys.argv) > 1 else "handjob/assets/sample_hands.jpg"
PALM = "build/models_lab/onnx/palm_detection_full.onnx"
LAND = "build/models_lab/onnx/hand_landmark_full.onnx"

frame = cv2.imread(IMG)
assert frame is not None, IMG
h, w = frame.shape[:2]

# ---------------- mediapipe (oracle) ----------------
from mediapipe import Image, ImageFormat
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

mp = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path="handjob/assets/hand_landmarker.task"),
    num_hands=1, running_mode=vision.RunningMode.VIDEO))
rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
mres = mp.detect_for_video(Image(image_format=ImageFormat.SRGB, data=rgb), 1)
mp_lm = None
if mres.hand_landmarks:
    mp_lm = np.array([(lm.x * w, lm.y * h) for lm in mres.hand_landmarks[0]])
mp_world = None
if mres.hand_world_landmarks:
    mp_world = np.array([(lm.x, lm.y, lm.z) for lm in mres.hand_world_landmarks[0]])
print(f"mediapipe: hands={len(mres.hand_landmarks)}")

# ---------------- onnx ----------------
t0 = time.perf_counter()
onnx = OnnxHandLandmarker(PALM, LAND)
print(f"providers: {onnx.backend()}  (init {1000*(time.perf_counter()-t0):.0f} ms)")
ores = onnx.detect_for_video(frame)
print(f"onnx: hands={len(ores.hand_landmarks)} score={ores.score:.3f}")
o_lm = None
if ores.hand_landmarks:
    o_lm = np.array([(p.x * w, p.y * h) for p in ores.hand_landmarks[0]])

if mp_lm is not None and o_lm is not None:
    d = np.linalg.norm(mp_lm - o_lm, axis=1)
    print(f"landmark deviation px: mean={d.mean():.1f} median={np.median(d):.1f} max={d.max():.1f}")
    print("per-point:", np.round(d, 1).tolist())

# world landmarks (used by the pinch metric)
if mp_world is not None and ores.hand_world_landmarks:
    ow = np.array([(p.x, p.y, p.z) for p in ores.hand_world_landmarks])
    print(f"world dev: mean={np.abs(mp_world-ow).mean():.4f} max={np.abs(mp_world-ow).max():.4f}")
    print("  mp wrist->mcp dist:", np.linalg.norm(mp_world[9]-mp_world[0]).round(4),
          " onnx:", np.linalg.norm(ow[9]-ow[0]).round(4))

# ---------------- visual ----------------
vis = frame.copy()
CONN = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
        (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18),
        (18, 19), (19, 20), (0, 17)]
if mp_lm is not None:
    for a, b in CONN:
        cv2.line(vis, tuple(mp_lm[a].astype(int)), tuple(mp_lm[b].astype(int)), (0, 220, 0), 2)
if o_lm is not None:
    for a, b in CONN:
        cv2.line(vis, tuple(o_lm[a].astype(int)), tuple(o_lm[b].astype(int)), (255, 0, 255), 1)
out = "build/onnx_e2e_vis.png"
cv2.imwrite(out, vis)
print("wrote", out)

# ---------------- timing (30 frames, steady state) ----------------
_ts = [1000]


def mp_call():
    _ts[0] += 1
    return mp.detect_for_video(Image(image_format=ImageFormat.SRGB, data=rgb), _ts[0])


for lbl, fn in (("onnx", lambda: onnx.detect_for_video(frame)), ("mediapipe", mp_call)):
    for _ in range(3):
        fn()
    t0 = time.perf_counter()
    n = 30
    for _ in range(n):
        fn()
    print(f"{lbl}: {(time.perf_counter()-t0)/n*1000:.2f} ms/frame  "
          f"(palm {onnx.stats['palm_ms']:.2f} + landmark {onnx.stats['land_ms']:.2f})" if lbl == "onnx"
          else f"{lbl}: {(time.perf_counter()-t0)/n*1000:.2f} ms/frame")
