"""Debug: raw palm box + landmark outputs + crop visual for the ONNX pipeline."""
import sys

import cv2
import numpy as np

sys.path.insert(0, ".")
from handjob.hand_onnx import OnnxHandLandmarker

PALM = "build/models_lab/onnx/palm_detection_full.onnx"
LAND = "build/models_lab/onnx/hand_landmark_full.onnx"

frame = cv2.imread("handjob/assets/sample_hands.jpg")
h, w = frame.shape[:2]
print("frame", frame.shape)

rt = OnnxHandLandmarker(PALM, LAND)

det = rt._palm_detect(frame)
print("palm det:", None if det is None else
      (f"score={det[0]:.3f} box=({det[1][0]:.0f},{det[1][1]:.0f},{det[1][2]:.0f},{det[1][3]:.0f}) "
       f"kp0=({det[2][0][0]:.0f},{det[2][0][1]:.0f}) kp2=({det[2][2][0]:.0f},{det[2][2][1]:.0f})"))
score, box, kps = det
crop, m = rt._crop(frame, box, kps)
cv2.imwrite("build/onnx_dbg_crop.png", crop)
outs = rt._landmark(crop)
lm = outs[0][0]
print("landmark out: min", lm.min().round(3), "max", lm.max().round(3), "head:", lm[:8].round(3))
wl = outs[3][0]
print("world out: min", wl.min().round(3), "max", wl.max().round(3))
print("presence", outs[1][0], "handed", outs[2][0])

inv = cv2.invertAffineTransform(m)
print("affine m:\n", m, "\ninv:\n", inv)
# where would crop-center map? should be the box center
cc = inv @ np.array([112.0, 112.0, 1.0])
print(f"crop-center maps to ({cc[0]:.0f},{cc[1]:.0f})  box center=({box[0]:.0f},{box[1]:.0f})")
# landmark 0 (wrist) mapped
for k in (0, 9):
    px, py = lm[2 * k] * 224.0, lm[2 * k + 1] * 224.0
    x = inv[0, 0] * px + inv[0, 1] * py + inv[0, 2]
    y = inv[1, 0] * px + inv[1, 1] * py + inv[1, 2]
    print(f"lm{k} crop=({px:.1f},{py:.1f}) -> image=({x:.0f},{y:.0f})")

# visualize crop with landmarks drawn
vis = crop.copy()
for k in range(21):
    cv2.circle(vis, (int(lm[2 * k] * 224), int(lm[2 * k + 1] * 224)), 3, (0, 0, 255), -1)
cv2.imwrite("build/onnx_dbg_crop_lm.png", vis)
print("wrote build/onnx_dbg_crop.png and onnx_dbg_crop_lm.png")
