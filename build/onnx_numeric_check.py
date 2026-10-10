"""Numeric check: converted ONNX vs the tflite runtime on identical input.

Run: .venv/Scripts/python.exe build/onnx_numeric_check.py
"""
import numpy as np
from ai_edge_litert.interpreter import Interpreter
import onnxruntime as ort


def run_tflite(path, x_nhwc):
    it = Interpreter(model_path=path)
    it.allocate_tensors()
    inp = it.get_input_details()[0]
    x = x_nhwc.astype(inp["dtype"])
    it.set_tensor(inp["index"], x)
    it.invoke()
    return [it.get_tensor(o["index"]) for o in it.get_output_details()]


def run_onnx(path, x):
    s = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    return s.run(None, {s.get_inputs()[0].name: x.astype(np.float32)})


rng = np.random.default_rng(3)

# palm: 192x192x3 NHWC tflite input
x = (rng.random((1, 192, 192, 3), np.float32) * 0.8 + 0.1)
tl = run_tflite("build/models_lab/palm_detection_full.tflite", x)
print("tflite palm outs:", [a.shape for a in tl])
xt = np.transpose(x, (0, 3, 1, 2))
on = run_onnx("build/models_lab/onnx/palm_detection_full.onnx", xt)
print("onnx palm outs:", [a.shape for a in on])
for i, (a, b) in enumerate(zip(tl, on)):
    a2 = a.reshape(-1)
    b2 = b.reshape(-1)
    d = np.abs(a2 - b2).max()
    print(f"  out{i}: tflite{a.shape} onnx{b.shape} max|d|={d:.4e}")

# keypoint row check: print raw row of the argmax anchor from both, first 8 values
sc_t = tl[1].reshape(-1)
i = int(np.argmax(sc_t))
print("argmax anchor:", i)
print("  tflite reg row:", np.round(tl[0].reshape(-1, 18)[i][:8], 3))
print("  onnx   reg row:", np.round(on[0].reshape(-1, 18)[i][:8], 3))

# landmark: 224
x2 = (rng.random((1, 224, 224, 3), np.float32) * 0.8 + 0.1)
tl2 = run_tflite("build/models_lab/hand_landmark_full.tflite", x2)
on2 = run_onnx("build/models_lab/onnx/hand_landmark_full.onnx", np.transpose(x2, (0, 3, 1, 2)))
print("landmark outs:", [a.shape for a in tl2])
for i, (a, b) in enumerate(zip(tl2, on2)):
    d = np.abs(a.reshape(-1) - b.reshape(-1)).max()
    print(f"  out{i}: max|d|={d:.4e}  tflite[0:3]={np.round(a.reshape(-1)[:3],3)} onnx[0:3]={np.round(b.reshape(-1)[:3],3)}")
