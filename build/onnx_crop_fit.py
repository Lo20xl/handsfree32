"""Fit MediaPipe's effective landmark crop by minimizing deviation vs the
mediapipe oracle: params (side_scale, shift_y, cx_off, cy_off) for the SAME
palm detection. Reveals which formula constant differs.

Run: .venv/Scripts/python.exe build/onnx_crop_fit.py [image]
"""
import sys

import cv2
import numpy as np

sys.path.insert(0, ".")
import handjob.hand_onnx as H

from mediapipe import Image, ImageFormat
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

mp = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path="handjob/assets/hand_landmarker.task"),
    num_hands=1, running_mode=vision.RunningMode.VIDEO))
rt = H.OnnxHandLandmarker("build/models_lab/onnx/palm_detection_full.onnx",
                          "build/models_lab/onnx/hand_landmark_lite.onnx")

img = cv2.imread(sys.argv[1] if len(sys.argv) > 1 else "build/e2e_hand_lower.png")
h, w = img.shape[:2]
rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
res = mp.detect_for_video(Image(image_format=ImageFormat.SRGB, data=rgb), 1)
ref = np.array([(lm.x * w, lm.y * h) for lm in res.hand_landmarks[0]])

det = rt._palm_detect(img)
score, box, kps = det


def evaluate(side_scale, shift_y, cx_off=0.0, cy_off=0.0):
    x, y, bw, bh = box
    box2 = (x + cx_off * bw, y + cy_off * bh, bw, bh)
    crop, m = rt._crop(img, box2, kps, rot_sign=1.0, side_scale=side_scale, shift_y=shift_y)
    outs = rt._landmark(crop)
    lm = outs[0][0].astype(np.float64)
    inv = cv2.invertAffineTransform(m)
    pts = np.array([(inv[0, 0] * lm[2 * k] + inv[0, 1] * lm[2 * k + 1] + inv[0, 2],
                     inv[1, 0] * lm[2 * k] + inv[1, 1] * lm[2 * k + 1] + inv[1, 2])
                    for k in range(21)])
    d = np.linalg.norm(ref - pts, axis=1)
    return d.mean(), pts


print("coarse sweep (side_scale, shift_y):")
rows = []
for ss in np.arange(1.6, 4.21, 0.2):
    for sh in np.arange(-0.8, 0.21, 0.2):
        dev, _ = evaluate(ss, sh)
        rows.append((dev, ss, sh))
rows.sort()
for dev, ss, sh in rows[:6]:
    print(f"  dev={dev:6.1f} side_scale={ss:.2f} shift_y={sh:.2f}")

best_dev, best_ss, best_sh = rows[0]
print("refine center offsets:")
rows2 = []
for cxo in np.arange(-0.4, 0.41, 0.1):
    for cyo in np.arange(-0.4, 0.41, 0.1):
        dev, _ = evaluate(best_ss, best_sh, cxo, cyo)
        rows2.append((dev, cxo, cyo))
rows2.sort()
for dev, cxo, cyo in rows2[:5]:
    print(f"  dev={dev:6.1f} cx_off={cxo:.1f} cy_off={cyo:.1f}")

dev, pts = evaluate(rows2[0][1] * 0 + best_ss, best_sh, rows2[0][1], rows2[0][2])
print(f"\nBEST: dev={dev:.1f} side={best_ss:.2f} shift={best_sh:.2f} cxo={rows2[0][1]:.1f} cyo={rows2[0][2]:.1f}")
print("oracle kp0/kp9 :", ref[0].round(1), ref[9].round(1))
print("onnx   kp0/kp9 :", pts[0].round(1), pts[9].round(1))
print("wrist->mcp dist: oracle", np.linalg.norm(ref[9] - ref[0]).round(1),
      " onnx", np.linalg.norm(pts[9] - pts[0]).round(1))
