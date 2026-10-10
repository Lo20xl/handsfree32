"""Fit crop params against the OFFICIAL expected landmarks on thumb_up.jpg."""
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
    pts = []
    for lm in re.finditer(r"landmark \{(.*?)\n  \}", m.group(1), re.S):
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
cx, cy, bw, bh = box
dx, dy = kps[2] - kps[0]
base_rot = math.pi / 2 - math.atan2(-dy, dx)
base_rot = (base_rot + math.pi) % (2 * math.pi) - math.pi
print(f"box px: ({cx:.0f},{cy:.0f},{bw:.0f},{bh:.0f}) base_rot={math.degrees(base_rot):.1f}deg")


def evaluate(rot_delta_deg, side_scale, shift, cx_off=0.0, cy_off=0.0):
    rot = base_rot + math.radians(rot_delta_deg)
    cx2 = cx + cx_off * bw
    cy2 = cy + cy_off * bh
    x_sh = -bh * shift * math.sin(rot)
    y_sh = bh * shift * math.cos(rot)
    cx2 += x_sh
    cy2 += y_sh
    side = max(bw, bh) * side_scale
    m = cv2.getRotationMatrix2D((cx2, cy2), math.degrees(rot), 224.0 / side)
    m[0, 2] += 112 - cx2
    m[1, 2] += 112 - cy2
    crop = cv2.warpAffine(img, m, (224, 224), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    outs = rt._landmark(crop)
    lm = outs[0][0].astype(float)
    inv = cv2.invertAffineTransform(m)
    pts = np.array([(inv[0, 0] * lm[2 * k] + inv[0, 1] * lm[2 * k + 1] + inv[0, 2],
                     inv[1, 0] * lm[2 * k] + inv[1, 1] * lm[2 * k + 1] + inv[1, 2]) for k in range(21)])
    d = np.linalg.norm((pts - exp) * [w, h], axis=1)
    return float(d.mean()), pts, crop


best = (1e9,)
for delta in (-20, -10, 0, 10, 20):
    for side_scale in (2.6, 3.0, 3.5, 4.0):
        for shift in (-0.8, -0.5, -0.2, 0.0):
            dev, _, _ = evaluate(delta, side_scale, shift)
            if dev < best[0]:
                best = (dev, delta, side_scale, shift)
print(f"coarse best: dev={best[0]:.1f} delta={best[1]} side={best[2]} shift={best[3]}")

# refine
b = best
for delta in np.arange(b[1] - 8, b[1] + 8.1, 2):
    for side_scale in np.arange(b[2] - 0.5, b[2] + 0.55, 0.25):
        for shift in np.arange(b[3] - 0.25, b[3] + 0.26, 0.1):
            for cxo, cyo in ((0, 0), (0, -0.15), (0, 0.15), (-0.15, 0), (0.15, 0)):
                dev, pts, crop = evaluate(delta, side_scale, shift, cxo, cyo)
                if dev < b[0]:
                    b = (dev, delta, side_scale, shift, cxo, cyo)
                    print(f"  dev={dev:6.1f} delta={delta:.0f} side={side_scale:.2f} shift={shift:.2f} off=({cxo},{cyo})")
print("FINAL:", "dev=%.1f delta=%.0f side=%.2f shift=%.2f off=(%s,%s)" % b)
