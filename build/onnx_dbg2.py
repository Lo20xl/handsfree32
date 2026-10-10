"""Visual: decoded palm box + 7 keypoints + resulting 224 crop."""
import sys

import cv2
import numpy as np

sys.path.insert(0, ".")
import handjob.hand_onnx as H

frame = cv2.imread("handjob/assets/sample_hands.jpg")
h, w = frame.shape[:2]
rt = H.OnnxHandLandmarker("build/models_lab/onnx/palm_detection_full.onnx",
                          "build/models_lab/onnx/hand_landmark_full.onnx")
det = rt._palm_detect(frame)
score, box, kps = det
print(f"score={score:.3f} box=({box[0]:.0f},{box[1]:.0f},{box[2]:.0f},{box[3]:.0f})")
print("kps:", np.round(kps, 1).tolist())

vis = frame.copy()
cx, cy, bw, bh = box
cv2.rectangle(vis, (int(cx - bw / 2), int(cy - bh / 2)), (int(cx + bw / 2), int(cy + bh / 2)),
              (0, 255, 0), 2)
for i, (kx, ky) in enumerate(kps):
    cv2.circle(vis, (int(kx), int(ky)), 4, (0, 0, 255), -1)
    cv2.putText(vis, str(i), (int(kx) + 4, int(ky) - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
# line wrist->mcp (kp0->kp2)
cv2.line(vis, (int(kps[0][0]), int(kps[0][1])), (int(kps[2][0]), int(kps[2][1])), (0, 255, 255), 2)
cv2.imwrite("build/onnx_dbg_kps.png", vis)

crop, m = rt._crop(frame, box, kps)
cv2.imwrite("build/onnx_dbg_crop2.png", crop)
print("wrote build/onnx_dbg_kps.png", "build/onnx_dbg_crop2.png")
