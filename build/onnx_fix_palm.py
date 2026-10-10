"""Fix up converted palm ONNX graphs: tflite2onnx's layout pass left PRelu
slope initializers as (1,1,C) (tflite NHWC-degenerate convention) where the
NCHW graph needs (1,C,1,1) (ORT PRelu broadcasts only from axis 1).

Run: .venv/Scripts/python.exe build/onnx_fix_palm.py
"""
import numpy as np
import onnx
from onnx import helper, numpy_helper


def fix(path):
    m = onnx.load(path)
    g = m.graph
    inits = {i.name: i for i in g.initializer}
    fixed = 0
    for n in g.node:
        if n.op_type != "PRelu" or len(n.input) < 2:
            continue
        sl = inits.get(n.input[1])
        if sl is None:
            continue
        arr = numpy_helper.to_array(sl)
        if arr.ndim == 3 and arr.shape[0] == 1 and arr.shape[1] == 1:
            new = arr.transpose(0, 2, 1).reshape(1, arr.shape[2], 1, 1)
            sl.CopyFrom(numpy_helper.from_array(np.ascontiguousarray(new), sl.name))
            fixed += 1
    if fixed:
        # refresh shapes for the moved initializers
        for vi in list(g.value_info):
            if vi.name in inits:
                g.value_info.remove(vi)
        m = onnx.shape_inference.infer_shapes(m, strict_mode=False)
        onnx.save(m, path)
    print(f"{path}: fixed {fixed} PRelu slopes")
    return fixed


if __name__ == "__main__":
    for p in ("build/models_lab/onnx/palm_detection_lite.onnx",
              "build/models_lab/onnx/palm_detection_full.onnx"):
        fix(p)
    # smoke: run both
    import onnxruntime as ort
    for p in ("build/models_lab/onnx/palm_detection_lite.onnx",
              "build/models_lab/onnx/palm_detection_full.onnx"):
        try:
            s = ort.InferenceSession(p, providers=["DmlExecutionProvider", "CPUExecutionProvider"])
            x = np.zeros((1, 3, 192, 192), np.float32)
            o = s.run(None, {s.get_inputs()[0].name: x})
            print(f"{p}: runs on {s.get_providers()[0]}  reg={o[0].shape} score={o[1].shape}")
        except Exception as e:
            print(f"{p}: STILL FAILS: {str(e)[:180]}")
