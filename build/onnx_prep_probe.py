"""Interpolation / letterbox variants on the palm model for pointing_up."""
import sys

import cv2
import numpy as np
import onnxruntime as ort

sess = ort.InferenceSession("build/models_lab/onnx/palm_detection_full.onnx",
                            providers=["CPUExecutionProvider"])
img = cv2.imread("build/pointing_up.jpg")
h, w = img.shape[:2]
s = min(192 / float(w), 192 / float(h))
rw, rh = int(round(w * s)), int(round(h * s))
pad_x = (192 - rw) // 2


def report(z, tag, scale, px):
    x = np.transpose(cv2.cvtColor(z, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0, (2, 0, 1))[None]
    reg, sc_raw = sess.run(None, {sess.get_inputs()[0].name: x})
    sc = 1 / (1 + np.exp(-np.clip(sc_raw[0, :, 0], -30, 30)))
    order = np.argsort(-sc)[:3]
    out = []
    for r in order:
        if r < 1152:
            cell = r // 2
            g = 24
        else:
            cell = ((r - 1152) % 288) // 2
            g = 12
        ix, iy = cell % g, cell // g
        cx = ((ix + 0.5) / g * 192 - px) / scale
        cy = ((iy + 0.5) / g * 192 - 0) / scale
        out.append(f"sc={sc[r]:.2f}@({cx:.0f},{cy:.0f})")
    print(f"{tag}: " + "  ".join(out))


z = np.zeros((192, 192, 3), np.uint8)
z[0:rh, pad_x:pad_x + rw] = cv2.resize(img, (rw, rh), interpolation=cv2.INTER_AREA)
report(z, "AREA letterbox   ", s, pad_x)
z = np.zeros((192, 192, 3), np.uint8)
z[0:rh, pad_x:pad_x + rw] = cv2.resize(img, (rw, rh), interpolation=cv2.INTER_LINEAR)
report(z, "LINEAR letterbox ", s, pad_x)
report(cv2.resize(img, (192, 192), interpolation=cv2.INTER_LINEAR), "stretch LINEAR   ", 192.0 / w, 0)
print("hand at (161,226); shadow left of hand at x~60-140")
