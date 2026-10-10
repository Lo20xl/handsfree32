#!/usr/bin/env bash
# Assemble HandJob3000-diagnostics-<ver>.zip (source + tools + docs + logs +
# camera evidence + state) into ~/Downloads and print the path.
set -e
cd ~/Desktop/HandJob3000
VER=$(grep -oE '[0-9]+\.[0-9]+\.[0-9]+' handjob/__init__.py | head -1)
STAGE="$HOME/Downloads/.hj3-diag-stage"
rm -rf "$STAGE"
D="$STAGE/HandJob3000-diagnostics-$VER"
mkdir -p "$D"/{01-src,02-tools,03-docs,04-logs,05-camera-evidence,06-state}

# 01 source (no pycache/baks, no bundled onnx models — regenerate via convert scripts)
tar cf - --exclude='__pycache__' --exclude='*.bak' --exclude='*.pyc' --exclude='hand_onnx' handjob ui tests | (cd "$D/01-src" && tar xf -)
cp -f build_installer.sh HandJob3000.spec stub.py handjob_run.py requirements-lock.txt setup_dev.sh "$D/01-src/" 2>/dev/null || true

# 02 diagnostic tools (build scripts; no binaries/big dirs/out churn)
tar cf - -C build --exclude='out' --exclude='from_claude*' --exclude='*.log' --exclude='superseded' \
  --exclude='models_lab' --exclude='HandJob3000' --exclude='HandJob3*' --exclude='HandJob4*' \
  --exclude='*.7z' --exclude='*.exe' --exclude='*.png' --exclude='*.jpg' --exclude='*.bin' \
  --exclude='*_out.txt' --exclude='*.pre*.bak' . | (cd "$D/02-tools" && tar xf -)

# 03 docs
cp -f README.md README-INSTALL.txt ARCHITECTURE.md DEBUGGING.md HANDJOB_REPORT.md "$D/03-docs/" 2>/dev/null || true

# 04 logs (installed app + repo + build/probe outputs + fresh test run)
cp -f "$LOCALAPPDATA/Programs/HandJob3000/handjob.log" "$D/04-logs/app-handjob.log" 2>/dev/null || true
cp -f "$LOCALAPPDATA/Programs/HandJob3000/crash.log" "$D/04-logs/app-crash.log" 2>/dev/null || true
cp -f handjob.log "$D/04-logs/repo-handjob.log" 2>/dev/null || true
cp -f crash.log "$D/04-logs/repo-crash.log" 2>/dev/null || true
for f in build/build25*.log build/cam_truth_out.txt build/real_cam_out.txt build/dev_probe_out.txt build/probe3000_out.txt build/camprobe_all_out.txt build/cursor_diag_out.txt; do
  [ -f "$f" ] && cp -f "$f" "$D/04-logs/$(basename "$f")" || true
done
.venv/Scripts/python.exe -m tests.test_handjob > "$D/04-logs/tests-latest.txt" 2>&1 || true

# 05 camera evidence (what cameras actually sent)
cp -f build/cam_truth_start.png build/cam_truth_mid.png build/cam_truth_end.png build/live_frame.png "$D/05-camera-evidence/" 2>/dev/null || true

# 06 state
cp -f "$LOCALAPPDATA/Programs/HandJob3000/settings.json" "$D/06-state/" 2>/dev/null || true

cat > "$D/00-README.txt" <<EOF
HandJob3000 diagnostics bundle — version $VER

CONTENTS
  01-src/    complete app source (handjob/, ui/, tests/) + build scripts
  02-tools/  every diagnostic tool (see below) — run from the repo root
  03-docs/   README, README-INSTALL, ARCHITECTURE.md (all fixes + causes),
             DEBUGGING.md (pipeline map, metrics, decision tree)
  04-logs/   installed-app log, build logs, probe outputs, fresh test run
  05-camera-evidence/  frames captured from the actual cameras
  06-state/  the installed app's settings.json

KEY TOOLS (in 02-tools, run from a source checkout via build/*_run_as_user.ps1)
  cam_truth_probe.py     what is a camera ACTUALLY sending: reads/s, new-frames/s,
                         bit-identical pair count, sample frames
  cam_probe_safe.py      can cameras be opened at all (hang-proof)
  real_cam_engine_check.py  runs the real engine 20 s against the camera
  probe3000_run_as_user.ps1  full hardware chain probe (packaged exe)
  tune_chain.py / tune_repeats.py  cursor-smoothness / repeating-camera harnesses

WHY THE APP SAID WHAT IT SAID
  "new frames/s" = how often the image actually CHANGED (16x16 gray signature).
  A camera can answer 60 reads/s while sending one still image (paused or
  disconnected source) — reads/s only prove the driver answers.
EOF

cd "$STAGE"
OUT="C:/Users/tangy/Downloads/HandJob3000-diagnostics-$VER.zip"
"/c/Program Files/7-Zip/7z.exe" a -tzip -mx=5 "$OUT" "HandJob3000-diagnostics-$VER" | tail -2
cd ~/Desktop/HandJob3000
rm -rf "$STAGE"
echo "DIAG_ZIP_DONE: $HOME/Downloads/HandJob3000-diagnostics-$VER.zip"
