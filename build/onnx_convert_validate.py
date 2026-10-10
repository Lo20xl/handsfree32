"""Convert all four mediapipe hand tflites to ONNX and CHECK NUMERICS against
the tflite runtime on random input. Any mismatch = conversion bug, do not ship.

Run: .venv/Scripts/python.exe build/onnx_convert_validate.py
"""
import os
import sys

import numpy as np

import tflite2onnx

SRC = "build/models_lab"
OUT = os.path.join(SRC, "onnx")
os.makedirs(OUT, exist_ok=True)

NAMES = ["hand_landmark_lite", "hand_landmark_full", "palm_detection_lite", "palm_detection_full"]


def convert_all():
    for name in NAMES:
        src, dst = f"{SRC}/{name}.tflite", f"{OUT}/{name}.onnx"
        if os.path.exists(dst):
            print(f"{name}: already converted")
            continue
        tflite2onnx.convert(src, dst)
        print(f"{name}: converted -> {dst}")


def validate(name, seed=7):
    from tflite import Interpreter  # tflite runtime (pip 'tflite')
    import onnxruntime as ort

    src, dst = f"{SRC}/{name}.tflite", f"{OUT}/{name}.onnx"
    ti = Interpreter(model_path=src)
    ti.allocate_tensors()
    inp = ti.get_input_details()[0]
    ishape = [int(d) for d in inp["shape"]]
    rng = np.random.default_rng(seed)
    x = rng.random(ishape, dtype=np.float32) * 2 - 1
    # tflite NCHW -> NHWC if needed? our models were converted to NCHW inputs;
    # tflite side expects the file's own input shape (usually NHWC)
    x_tfl = x
    ti.set_tensor(inp["index"], x_tfl)
    ti.invoke()
    tfl_out = [ti.get_tensor(o["index"]) for o in ti.get_output_details()]

    sess = ort.InferenceSession(dst, providers=["CPUExecutionProvider"])
    onnx_in = sess.get_inputs()[0]
    oshape = [d if isinstance(d, int) else 1 for d in onnx_in.shape]
    x_onnx = x.reshape(oshape) if np.prod(oshape) == x.size else x
    # NCHW input in ONNX vs NHWC in tflite: transpose when channel-first
    if oshape[1] == ishape[-1] and len(oshape) == 4:
        x_onnx = np.transpose(x, (0, 3, 1, 2))
    onnx_out = sess.run(None, {onnx_in.name: x_onnx.astype(np.float32)})

    print(f"\n{name}: tflite {len(tfl_out)} outputs vs onnx {len(onnx_out)} outputs")
    np.set_printoptions(precision=4, suppress=True, linewidth=150)
    ok = True
    for i, (a, b) in enumerate(zip(tfl_out, onnx_out)):
        a, b = np.asarray(a), np.asarray(b)
        if a.shape != b.shape:
            # tflite NHWC-ish vs onnx NCHW-ish output shape: compare values sorted-by-flat max-abs
            if a.size == b.size:
                d = float(np.abs(a.reshape(-1) - b.reshape(-1)).max())
                print(f"  out{i}: shape differs tflite{a.shape} onnx{b.shape} (flat max|d|={d:.4f})")
                ok = ok and d < 1e-2
            else:
                print(f"  out{i}: SHAPE MISMATCH tflite{a.shape} vs onnx{b.shape} (sizes {a.size}/{b.size})")
                ok = False
            continue
        d = float(np.abs(a - b).max())
        rate = float(np.mean(np.abs(a - b) > 1e-3))
        print(f"  out{i}: max|d|={d:.5f} frac>1e-3={rate:.4f}")
        ok = ok and d < 5e-3
    return ok


if __name__ == "__main__":
    convert_all()
    all_ok = True
    for n in NAMES:
        try:
            all_ok = validate(n) and all_ok
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"{n}: VALIDATION FAILED to run: {e}")
            all_ok = False
    print("\nNUMERICS_OK" if all_ok else "\nNUMERICS_FAIL")
