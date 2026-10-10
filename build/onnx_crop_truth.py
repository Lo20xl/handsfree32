"""Map the OFFICIAL expected landmarks into MY crop: if they form a good hand
there, my crop matches MediaPipe's; if not, the crop geometry is wrong.

Run: .venv/Scripts/python.exe build/onnx_crop_truth.py
"""
import math
import re
import sys

import cv2
import numpy as np

sys.path.insert(0, ".")
import handjob.hand_onnx as H

CONN = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
        (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18),
        (18, 19), (19, 20), (0, 17)]


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
crop, m = rt._crop(img, box, kps)
outs = rt._landmark(crop)
on = outs[0][0].astype(float)

vis = crop.copy()
# expected landmarks mapped INTO the crop space
exp_pts = np.array([(exp[k][0] * w, exp[k][1] * h) for k in range(21)], np.float32)
exp_crop = cv2.transform(exp_pts.reshape(-1, 1, 2), m).reshape(-1, 2)
for a, b in CONN:
    cv2.line(vis, tuple(exp_crop[a].astype(int)), tuple(exp_crop[b].astype(int)), (0, 220, 0), 1)
    cv2.line(vis, (int(on[2 * a]), int(on[2 * a + 1])), (int(on[2 * b]), int(on[2 * b + 1])), (255, 0, 255), 1)
for k in range(21):
    cv2.circle(vis, tuple(exp_crop[k].astype(int)), 2, (0, 160, 0), -1)
    cv2.circle(vis, (int(on[2 * k]), int(on[2 * k + 1])), 2, (255, 0, 255), -1)
cv2.imwrite("build/thumb_up_crop_truth.png", vis)
print("wrote build/thumb_up_crop_truth.png")
print("exp in crop: x", exp_crop[:, 0].min().round(0), exp_crop[:, 0].max().round(0),
      " y", exp_crop[:, 1].min().round(0), exp_crop[:, 1].max().round(0))
print("onnx in crop: x", on[0::3].min().round(0), on[0::3].max().round(0),
      " y", on[1::3].min().round(0), on[1::3].max().round(0))
print("crop side px:", max(box[2], box[3]) * 2.6, "box:", [round(v) for v in box])
