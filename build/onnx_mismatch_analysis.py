"""Numeric characterization of onnx-vs-expected mismatch on thumb_up.jpg."""
import math
import re
import sys

import cv2
import numpy as np

sys.path.insert(0, ".")
import handjob.hand_onnx as H


def parse_expected(path):
    txt = open(path, encoding="utf-8").read()
    m = re.search(r"\nlandmarks \{(.*?)\n\}\n", txt, re.S)
    body = m.group(1)
    pts = []
    for lm in re.finditer(r"landmark \{(.*?)\n  \}", body, re.S):
        blk = lm.group(1)
        x = re.search(r"x:\s*([-\d.eE]+)", blk)
        y = re.search(r"y:\s*([-\d.eE]+)", blk)
        if x and y:
            pts.append((float(x.group(1)), float(y.group(1))))
    return np.array(pts)


img = cv2.imread("build/thumb_up.jpg")
h, w = img.shape[:2]
exp = parse_expected("build/thumb_up_landmarks.pbtxt")
rt = H.OnnxHandLandmarker("build/models_lab/onnx/palm_detection_full.onnx",
                          "build/models_lab/onnx/hand_landmark_lite.onnx")
score, box, kps = rt._palm_detect(img)
o = rt.detect_for_video(img)
on = np.array([(p.x, p.y) for p in o.hand_landmarks[0]])
print("palm:", round(score, 3), "box px:", [round(v) for v in box])
print("kps px:", np.round(kps).astype(int).tolist())

for tag, pts in (("exp ", exp), ("onnx", on)):
    k0, k9 = pts[0], pts[9]
    v = np.array([(k9[0] - k0[0]) * w, (k9[1] - k0[1]) * h])
    ang = math.degrees(math.atan2(v[1], v[0]))
    print(f"{tag}: kp0=({k0[0]*w:5.0f},{k0[1]*h:5.0f})  kp9=({k9[0]*w:5.0f},{k9[1]*h:5.0f})  "
          f"wrist->mcp=({v[0]:6.1f},{v[1]:6.1f}) len={np.linalg.norm(v):5.1f} ang={ang:6.1f}")

A, b = [], []
for (px, py), (rx, ry) in zip(on, exp):
    A.append([px, -py, 1, 0])
    b.append(rx)
    A.append([py, px, 0, 1])
    b.append(ry)
sol, *_ = np.linalg.lstsq(np.array(A, float), np.array(b, float), rcond=None)
a, bv, tx, ty = sol
print(f"similarity onnx->exp: scale={math.hypot(a, bv):.3f} "
      f"rot={math.degrees(math.atan2(bv, a)):.1f}deg trans px=({tx*w:.0f},{ty*h:.0f})")
pred = np.array([(a * px - bv * py + tx, bv * px + a * py + ty) for px, py in on])
print("residual after similarity:", np.linalg.norm((pred - exp) * [w, h], axis=1).mean().round(1), "px")
