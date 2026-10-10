"""Draw oracle (green) vs onnx (magenta) skeletons + numbered dots on one image."""
import sys

import cv2
import numpy as np

sys.path.insert(0, ".")
import handjob.hand_onnx as H
from mediapipe import Image, ImageFormat
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

img_path = sys.argv[1] if len(sys.argv) > 1 else "build/e2e_hand_lower.png"
img = cv2.imread(img_path)
h, w = img.shape[:2]

mp = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path="handjob/assets/hand_landmarker.task"),
    num_hands=1, running_mode=vision.RunningMode.VIDEO))
rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
res = mp.detect_for_video(Image(image_format=ImageFormat.SRGB, data=rgb), 1)
ref = np.array([(lm.x * w, lm.y * h) for lm in res.hand_landmarks[0]])

rt = H.OnnxHandLandmarker("build/models_lab/onnx/palm_detection_full.onnx",
                          "build/models_lab/onnx/hand_landmark_lite.onnx")
o = rt.detect_for_video(img)
pts = np.array([(p.x * w, p.y * h) for p in o.hand_landmarks[0]])

CONN = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
        (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18),
        (18, 19), (19, 20), (0, 17)]
vis = img.copy()
for a, b in CONN:
    cv2.line(vis, tuple(ref[a].astype(int)), tuple(ref[b].astype(int)), (0, 220, 0), 2)
    cv2.line(vis, tuple(pts[a].astype(int)), tuple(pts[b].astype(int)), (255, 0, 255), 1)
for i in range(21):
    cv2.circle(vis, tuple(ref[i].astype(int)), 2, (0, 120, 0), -1)
    cv2.circle(vis, tuple(pts[i].astype(int)), 2, (255, 0, 255), -1)
for i, p in enumerate(pts):
    if i % 4 == 0:
        cv2.putText(vis, f"o{i}", (int(p[0]) + 3, int(p[1]) - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 255), 1)
        cv2.putText(vis, f"m{i}", (int(ref[i][0]) + 3, int(ref[i][1]) + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 120, 0), 1)
out = img_path.replace(".png", "_cmp.png")
cv2.imwrite(out, vis)
print("wrote", out)
print("onnx kp0:", pts[0].round(1), " oracle kp0:", ref[0].round(1))
print("onnx kp9:", pts[9].round(1), " oracle kp9:", ref[9].round(1))
print("onnx kp12:", pts[12].round(1), " oracle kp12:", ref[12].round(1))
