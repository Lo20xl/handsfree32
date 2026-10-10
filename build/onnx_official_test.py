"""Definitive calibration test: my ONNX pipeline vs MediaPipe's OFFICIAL
expected output (thumb_up_landmarks.pbtxt from the mediapipe repo) + vs the
mediapipe runtime, on the canonical test images.

Run from repo root: .venv/Scripts/python.exe build/onnx_official_test.py
"""
import re
import sys

import cv2
import numpy as np

sys.path.insert(0, ".")
import handjob.hand_onnx as H

from mediapipe import Image, ImageFormat
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions


def parse_expected(path):
    """Parse the mediapipe expected-landmarks prototxt -> Nx3 array (normalized)."""
    txt = open(path, encoding="utf-8").read()
    # first landmarks { ... } block after the classifications
    m = re.search(r"\nlandmarks \{(.*?)\n\}\n", txt, re.S)
    assert m, "no landmarks block"
    body = m.group(1)
    pts = []
    for lm in re.finditer(r"landmark \{(.*?)\n  \}", body, re.S):
        blk = lm.group(1)
        x = re.search(r"x:\s*([-\d.eE]+)", blk)
        y = re.search(r"y:\s*([-\d.eE]+)", blk)
        z = re.search(r"z:\s*([-\d.eE]+)", blk)
        if x and y:
            pts.append((float(x.group(1)), float(y.group(1)),
                        float(z.group(1)) if z else 0.0))
    return np.array(pts)


mp = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path="handjob/assets/hand_landmarker.task"),
    num_hands=1, running_mode=vision.RunningMode.VIDEO))
rt = H.OnnxHandLandmarker("build/models_lab/onnx/palm_detection_full.onnx",
                          "build/models_lab/onnx/hand_landmark_lite.onnx")

for _i, name in enumerate(("thumb_up", "pointing_up")):
    img = cv2.imread(f"build/{name}.jpg")
    h, w = img.shape[:2]
    exp = parse_expected(f"build/{name}_landmarks.pbtxt")
    print(f"\n=== {name}.jpg ({w}x{h}) expected {len(exp)} landmarks ===")

    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    res = mp.detect_for_video(Image(image_format=ImageFormat.SRGB, data=rgb), _i + 1)
    mp_lm = np.array([(lm.x, lm.y) for lm in res.hand_landmarks[0]]) if res.hand_landmarks else None

    o = rt.detect_for_video(img)
    on_lm = np.array([(p.x, p.y) for p in o.hand_landmarks[0]]) if o.hand_landmarks else None

    def dev(a, b, tag):
        if a is None or b is None:
            print(f"  {tag}: MISSING (a={a is not None} b={b is not None})")
            return
        a2, b2 = np.asarray(a)[:, :2], np.asarray(b)[:, :2]
        d = np.linalg.norm((a2 - b2) * np.array([w, h]), axis=1)
        print(f"  {tag}: mean={d.mean():.1f}px median={np.median(d):.1f}px max={d.max():.1f}px")

    dev(mp_lm, exp, "mediapipe vs expected")
    dev(on_lm, exp, "onnx      vs expected")
    dev(on_lm, mp_lm, "onnx      vs mediapipe")

    # visual
    vis = img.copy()
    CONN = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
            (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18),
            (18, 19), (19, 20), (0, 17)]
    for a, b in CONN:
        pa = tuple((exp[a][:2] * [w, h]).astype(int))
        pb = tuple((exp[b][:2] * [w, h]).astype(int))
        cv2.line(vis, pa, pb, (0, 220, 0), 1)
    if on_lm is not None:
        for a, b in CONN:
            pa = tuple((on_lm[a] * [w, h]).astype(int))
            pb = tuple((on_lm[b] * [w, h]).astype(int))
            cv2.line(vis, pa, pb, (255, 0, 255), 1)
    cv2.imwrite(f"build/{name}_cmp.png", vis)
    print(f"  wrote build/{name}_cmp.png (green=expected, magenta=onnx)... plus details:")
    if on_lm is not None:
        for k in (0, 9, 12):
            print(f"    kp{k}: exp={np.round(exp[k][:2]*[w,h],1)} onnx={np.round(on_lm[k]*[w,h],1)}")
