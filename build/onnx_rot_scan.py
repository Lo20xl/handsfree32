"""2D scan: rotation delta (vs C++ formula) x side_scale, minimizing deviation
vs the mediapipe oracle on the test images. Reveals the exact remaining offset.

Run: .venv/Scripts/python.exe build/onnx_rot_scan.py
"""
import math
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


_TS = [1000]


def oracle(img):
    h, w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    _TS[0] += 1
    res = mp.detect_for_video(Image(image_format=ImageFormat.SRGB, data=rgb), _TS[0])
    if not res.hand_landmarks:
        return None
    return np.array([(lm.x * w, lm.y * h) for lm in res.hand_landmarks[0]])


def eval_params(img, det, rot_delta_deg, side_scale, shift):
    h, w = img.shape[:2]
    ref = oracle(img)
    if ref is None:
        return 1e9
    score, box, kps = det
    cx, cy, bw, bh = box
    dx, dy = kps[2] - kps[0]
    rot = math.pi / 2 - math.atan2(-dy, dx)
    rot = (rot + math.pi) % (2 * math.pi) - math.pi
    rot += math.radians(rot_delta_deg)
    x_sh = -bh * shift * math.sin(rot)
    y_sh = bh * shift * math.cos(rot)
    cx2, cy2 = cx + x_sh, cy + y_sh
    side = max(bw, bh) * side_scale
    m = cv2.getRotationMatrix2D((cx2, cy2), math.degrees(rot), 224.0 / side)
    m[0, 2] += 112 - cx2
    m[1, 2] += 112 - cy2
    crop = cv2.warpAffine(img, m, (224, 224), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    outs = rt._landmark(crop)
    lm = outs[0][0].astype(float)
    inv = cv2.invertAffineTransform(m)
    pts = np.array([(inv[0, 0] * lm[2 * k] + inv[0, 1] * lm[2 * k + 1] + inv[0, 2],
                     inv[1, 0] * lm[2 * k] + inv[1, 1] * lm[2 * k + 1] + inv[1, 2])
                    for k in range(21)])
    return float(np.linalg.norm(ref - pts, axis=1).mean())


imgs = ["build/e2e_hand_lower.png", "build/e2e_hand_raised.png"]
dets = [rt._palm_detect(cv2.imread(p)) for p in imgs]
print("dets:", [(None if d is None else round(d[0], 3)) for d in dets])

results = []
for delta in range(-90, 91, 15):
    for ss in (1.6, 2.0, 2.6, 3.1):
        devs = []
        for img_path, det in zip(imgs, dets):
            if det is None:
                continue
            img = cv2.imread(img_path)
            devs.append(eval_params(img, det, delta, ss, -0.5))
        results.append((float(np.mean(devs)), delta, ss))
results.sort()
print(f"{'dev':>7} {'rot_delta':>10} {'side':>6}")
for dev, delta, ss in results[:12]:
    print(f"{dev:7.1f} {delta:10} {ss:6.2f}")
