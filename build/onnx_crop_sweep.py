"""Sweep crop parameters against the mediapipe oracle on single-hand images.

Run: .venv/Scripts/python.exe build/onnx_crop_sweep.py
"""
import sys

import cv2
import numpy as np

sys.path.insert(0, ".")
from handjob.hand_onnx import OnnxHandLandmarker

from mediapipe import Image, ImageFormat
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

mp = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path="handjob/assets/hand_landmarker.task"),
    num_hands=1, running_mode=vision.RunningMode.VIDEO))
rt = OnnxHandLandmarker("build/models_lab/onnx/palm_detection_full.onnx",
                        "build/models_lab/onnx/hand_landmark_full.onnx")


def oracle(frame):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    res = mp.detect_for_video(Image(image_format=ImageFormat.SRGB, data=rgb), 1)
    if not res.hand_landmarks:
        return None
    h, w = frame.shape[:2]
    return np.array([(lm.x * w, lm.y * h) for lm in res.hand_landmarks[0]])


def run_variant(frame, det, rot_sign, side_scale, shift_y):
    score, box, kps = det
    crop, m = rt._crop(frame, box, kps, rot_sign=rot_sign, side_scale=side_scale, shift_y=shift_y)
    outs = rt._landmark(crop)
    lm = outs[0][0].astype(np.float64)
    presence = float(outs[1][0][0])
    h, w = frame.shape[:2]
    inv = cv2.invertAffineTransform(m)
    pts = []
    for k in range(21):
        px, py = lm[2 * k], lm[2 * k + 1]
        x = inv[0, 0] * px + inv[0, 1] * py + inv[0, 2]
        y = inv[1, 0] * px + inv[1, 1] * py + inv[1, 2]
        pts.append((x, y))
    return np.array(pts), presence, crop


img = cv2.imread(sys.argv[1] if len(sys.argv) > 1 else "build/e2e_hand_lower.png")
ref = oracle(img)
print("oracle:", "found" if ref is not None else "NONE")
det = rt._palm_detect(img)
score, box, kps = det
print(f"palm: score={score:.3f} box=({box[0]:.0f},{box[1]:.0f},{box[2]:.0f},{box[3]:.0f})")
print("kps:", np.round(kps).tolist())
dx, dy = kps[2] - kps[0]
print(f"wrist->mcp px: ({dx:.1f},{dy:.1f}) len={np.hypot(dx, dy):.1f}")

print(f"{'rot_sign':>8} {'side':>5} {'shift':>6} {'dev_mean':>9} {'dev_max':>8} {'presence':>8}")
best = None
for rot_sign in (1.0, -1.0):
    for side_scale in (2.05, 2.6, 3.1, 3.5):
        for shift_y in (-0.5, 0.0):
            pts, presence, crop = run_variant(img, det, rot_sign, side_scale, shift_y)
            d = np.linalg.norm(ref - pts, axis=1)
            print(f"{rot_sign:8.1f} {side_scale:5.2f} {shift_y:6.1f} {d.mean():9.1f} {d.max():8.1f} {presence:8.3f}")
            if best is None or d.mean() < best[0]:
                best = (d.mean(), rot_sign, side_scale, shift_y, crop)
print(f"BEST: dev={best[0]:.1f} rot_sign={best[1]} side={best[2]} shift={best[3]}")
cv2.imwrite("build/onnx_sweep_best_crop.png", best[4])
