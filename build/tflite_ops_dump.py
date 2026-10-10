"""Dump ops/tensors of a tflite file (to see why tflite2onnx fails on palm_detection)."""
import sys

from tflite import Model

path = sys.argv[1] if len(sys.argv) > 1 else "build/models_lab/palm_detection_lite.tflite"
buf = open(path, "rb").read()
m = Model.GetRootAsModel(buf, 0)
sg = m.Subgraphs(0)
print(f"inputs: {[(sg.Inputs(i), sg.Tensors(sg.Inputs(i)).Name().decode()) for i in range(sg.InputsLength())]}")
print(f"outputs: {[(sg.Outputs(i), sg.Tensors(sg.Outputs(i)).Name().decode()) for i in range(sg.OutputsLength())]}")
for i in range(sg.OutputsLength()):
    t = sg.Tensors(sg.Outputs(i))
    print(f"  out tensor {t.Name().decode()}: shape={[t.Shape(j) for j in range(t.ShapeLength())]} type={t.Type()}")
names = {}
for i in range(sg.OperatorsLength()):
    op = sg.Operators(i)
    oc = m.OperatorCodes(op.OpcodeIndex())
    if oc.BuiltinCode() == 32:  # CUSTOM
        code = oc.CustomCode().decode() if oc.CustomCode() else "?"
    else:
        code = f"builtin:{oc.BuiltinCode()}"
    names[code] = names.get(code, 0) + 1
print("op histogram:", names)
