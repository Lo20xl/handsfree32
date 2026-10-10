#!/usr/bin/env bash
# Build HandJob3000.exe + installer. Run: bash build_installer.sh > build/build.log 2>&1
set -x
cd ~/Desktop/HandJob3000 || exit 1
mkdir -p build dist dist-installer

# --- clean stale process + old build (exe locks block rebuilds) ---
taskkill //F //IM HandJob3000.exe 2>/dev/null
rm -rf dist/HandJob3000 build/HandJob3000

# --- PyInstaller ---
.venv/Scripts/pyinstaller.exe --noconfirm --clean --onedir --noconsole \
  --name HandJob3000 \
  --icon assets/icon.ico \
  --add-data "ui;ui" \
  --add-data "handjob/assets;assets" \
  --collect-all mediapipe \
  --collect-all webview \
  --collect-all clr_loader \
  --collect-all pythonnet \
  --collect-all sounddevice \
  --collect-all pygrabber \
  --collect-all comtypes \
  --collect-all onnxruntime \
  --hidden-import stub \
  --exclude-module pythoncom --exclude-module pywin32 \
  stub.py

# --- strip GPU/DirectML bloat if present (CPU-only app) ---
find "dist/HandJob3000" \( -iname "cublas*" -o -iname "cufft*" -o -iname "cudnn*" \
  -o -iname "cuda*.dll" -o -iname "onnxruntime_providers_cuda.dll" \
  -o -iname "onnxruntime_providers_tensorrt.dll" -o -iname "*directml*" \) -delete 2>/dev/null

echo "=== dist size ==="
du -sh dist/HandJob3000
echo "=== top 20 files ==="
find dist/HandJob3000 -type f -printf "%s %p\n" 2>/dev/null | sort -rn | head -20
echo "=== key files present? ==="
ls -la dist/HandJob3000/_internal/assets/hand_landmarker.task dist/HandJob3000/_internal/ui/index.html dist/HandJob3000/HandJob3000.exe

# --- smoke: frozen self-test (model load) in THIS session ---
echo "=== frozen selftest ==="
"dist/HandJob3000/HandJob3000.exe" --selftest 2>&1 | tail -5
echo "selftest_exit=$?"

# --- Inno Setup ---
ISCC=""
for p in "/c/Program Files (x86)/Inno Setup 6/ISCC.exe" "/c/Program Files/Inno Setup 6/ISCC.exe" "$HOME/AppData/Local/Programs/Inno Setup 6/ISCC.exe"; do
  [ -f "$p" ] && ISCC="$p" && break
done
if [ -n "$ISCC" ]; then
  "$ISCC" build/installer.iss
  echo "INNO_EXIT=$?"
  ls -la dist-installer/
else
  echo "INNO_MISSING - fallback to 7z SFX"
  SFX="/c/Users/tangy/scoop/apps/7zip/current/7z.sfx"
  "/c/Program Files/7-Zip/7z.exe" a -t7z -mx=5 build/HandJob3000.7z ./dist/HandJob3000/ 
  cat "$SFX" build/sfx_config.txt build/HandJob3000.7z > dist-installer/HandJob3000-Setup-2.5.6.exe
  .venv/Scripts/python.exe -c "d=open('dist-installer/HandJob3000-Setup-2.5.6.exe','rb').read(2); assert d==b'MZ', 'SFX header wrong!'; print('SFX_OK')"
fi
echo BUILD_SCRIPT_DONE
