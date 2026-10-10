"""GPU port spike: convert the MediaPipe hand tflites to ONNX and smoke-test
inference on the DirectML execution provider (RTX 5070).

Run: .venv/Scripts/python.exe build/onnx_spike.py
"""
import os
import sys
import time

import numpy as np
import onnx
import onnxruntime as ort
import tflite2onnx

SRC = "build/models_lab"
OUT = "build/models_lab/onnx"
os.makedirs(OUT, exist_ok=True)

names = ["hand_landmark_lite", "hand_landmark_full", "palm_detection_lite", "palm_detection_full"]
for name in names:
    src = f"{SRC}/{name}.tflite"
    dst = f"{OUT}/{name}.onnx"
    if not os.path.exists(src):
        print(f"{name}: SOURCE MISSING ({src})")
        continue
    try:
        tflite2onnx.convert(src, dst)
        m = onnx.load(dst)
        ins = [(i.name, [d.dim_value for d in i.type.tensor_type.shape.dim]) for i in m.graph.input]
        outs = [(o.name, [d.dim_value for d in o.type.tensor_type.shape.dim]) for o in m.graph.output]
        customs = sorted({n.domain for n in m.graph.node if n.domain not in ("", "ai.onnx")})
        print(f"{name}: OK\n  inputs : {ins}\n  outputs: {outs}\n  custom domain ops: {customs or 'none'}")
    except Exception as e:
        print(f"{name}: FAIL {type(e).__name__}: {str(e)[:250]}")

print("\nOR: available providers:", ort.get_available_providers())

for name in ("hand_landmark_lite", "hand_landmark_full"):
    path = f"{OUT}/{name}.onnx"
    if not os.path.exists(path):
        continue
    for prov in (["DmlExecutionProvider", "CPUExecutionProvider"], ["CPUExecutionProvider"]):
        try:
            sess = ort.InferenceSession(path, providers=prov)
            inp = sess.get_inputs()[0]
            shp = [d if isinstance(d, int) else 1 for d in inp.shape]
            x = np.zeros(shp, dtype=np.float32)
            feed = {inp.name: x}
            for _ in range(3):
                sess.run(None, feed)
            t0 = time.perf_counter()
            n = 40
            for _ in range(n):
                sess.run(None, feed)
            ms = (time.perf_counter() - t0) / n * 1000
            print(f"{name} [{'+'.join(p[:3] for p in sess.get_providers())}]: {ms:.2f} ms/frame")
        except Exception as e:
            print(f"{name} [{prov[0]}]: FAIL {type(e).__name__}: {str(e)[:200]}")
