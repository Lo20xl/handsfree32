#!/usr/bin/env bash
# HandJob3000 dev setup: venv + deps + test assets. Logs to setup.log
set -x
cd ~/Desktop/HandJob3000 || exit 1
mkdir -p handjob ui tests assets build

uv venv --python 3.12 .venv 2>&1 | tail -2
VP=".venv/Scripts/python.exe"

uv pip install --python "$VP" mediapipe opencv-contrib-python pillow pywebview pyinstaller 2>&1 | tail -6

# --- probe what we actually got ---
"$VP" - <<'PY'
import sys, json
info = {}
import mediapipe as mp
info["python"] = sys.version.split()[0]
info["mediapipe"] = mp.__version__
try:
    import mediapipe.python.solutions as sol
    info["solutions_hands"] = hasattr(sol, "hands")
except Exception as e:
    info["solutions_hands"] = f"ERR {e}"
import cv2; info["cv2"] = cv2.__version__
import PIL; info["pillow"] = PIL.__version__
try:
    import webview; info["pywebview"] = webview.__version__
except Exception as e:
    info["pywebview"] = f"ERR {e}"
import PyInstaller; info["pyinstaller"] = PyInstaller.__version__
import numpy; info["numpy"] = numpy.__version__
print("PROBE_JSON:" + json.dumps(info))
PY

# --- test image (mediapipe sample) with fallbacks ---
URLS=(
 "https://storage.googleapis.com/mediapipe-tasks/hand_landmarker/woman_hands.jpg"
 "https://storage.googleapis.com/mediapipe-assets/woman_hands.jpg"
)
for u in "${URLS[@]}"; do
  curl -sfL --max-time 60 -o assets/woman_hands.jpg "$u" && break
done
"$VP" -c "import cv2; im=cv2.imread('assets/woman_hands.jpg'); print('TESTIMAGE:', im is not None, None if im is None else im.shape)"

# --- icon ---
"$VP" - <<'PY'
from PIL import Image, ImageDraw
S=256
img=Image.new("RGBA",(S,S),(0,0,0,0))
d=ImageDraw.Draw(img)
d.rounded_rectangle([8,8,S-8,S-8],radius=52,fill=(13,13,13,255))
cx=cy=S//2
for r,a in [(96,18),(78,34),(62,58),(48,92),(34,150),(22,220)]:
    d.ellipse([cx-r,cy-r,cx+r,cy+r],fill=(56,189,248,a))
d.ellipse([cx-16,cy-16,cx+16,cy+16],fill=(255,255,255,255))
d.ellipse([cx-8,cy-10,cx-2,cy-4],fill=(224,246,255,255))
# sparkle
def star(x,y,r):
    d.polygon([(x,y-r),(x+r*0.22,y-r*0.22),(x+r,y),(x+r*0.22,y+r*0.22),(x,y+r),(x-r*0.22,y+r*0.22),(x-r,y),(x-r*0.22,y-r*0.22)],fill=(255,255,255,235))
star(190,70,26); star(70,196,16)
img.save("assets/icon.ico", sizes=[(256,256),(64,64),(48,48),(32,32),(16,16)])
img.save("assets/icon.png")
print("ICON_OK")
PY

"$VP" -m pip freeze > requirements-lock.txt 2>/dev/null || "uv pip freeze --python .venv" > requirements-lock.txt
echo BUILD_SETUP_DONE
