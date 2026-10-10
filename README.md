# HandJob3000

Hand-gesture mouse control for Windows 10/11. Webcam hand tracking by
MediaPipe drives the real cursor, clicks, drags and scroll through Win32
`SendInput`, with a custom on-screen cursor (the "sky orb") rendered by a
click-through layered window. Everything is local — no network, no accounts,
camera frames never leave the machine.

Point with your index finger: the cursor follows the fingertip, the point you
actually aim with.

## Gestures

| Gesture | Action |
|---|---|
| Point (index up) | Move cursor — follows the index fingertip |
| Pinch thumb + middle | Left click — hold & move to drag (sparkle trail) |
| Pinch thumb + ring | Right click |
| Peace sign (index + middle), move hand up/down | Scroll |
| Open palm / fist / pinky out | Pause cursor (clutch — re-position your hand freely) |
| Second hand appears | Ignored — control stays on the first (primary) hand |
| Ctrl+Alt+H | Panic stop — instantly disarms control |

## Install

Grab `HandJob3000-Setup-<version>.exe` from the **Releases** page and run it —
per-user install (no admin rights), desktop shortcut optional, uninstaller
included.

## Why it feels smooth (the hard part)

A webcam is not a mouse: 10–60 jittery position samples per second must become
a steady 144 Hz cursor stream. The pipeline:

```
camera → landmark stabilizer (adaptive 1€ filter + spike gate + palm guard)
       → travel mapping → click/drag refiner
       → CursorMotion (interpolation + prediction + rest-hold, 144 Hz emitter)
       → SendInput
```

- **Repeat-frame gate**: virtual cameras (Camo, NVIDIA Broadcast, OBS) answer
  every read by repeating the last frame. Repeats are detected and dropped
  before tracking, so every timing/velocity estimate stays honest — and ~80%
  of the CPU work is skipped on such cameras.
- **Anti-jitter core**: adaptive landmark filtering, speed-gated prediction
  that hides camera+inference latency while moving, and a rest-hold stage
  that keeps a still hand rock-steady with zero added lag in motion.
- **Dedicated emitter thread** (high priority, 144 Hz) owns all cursor moves;
  the overlay draws in lock-step with it (dirty-rect layered window).
- **Watchdogs**: camera stall → reopen; frozen virtual cam (source died) →
  cursor halts + a clear message; dim-light/repeat-frame warnings; Ctrl+Alt+H
  panic stop.

Tuning decisions are measured, not vibes: `build/tune_chain.py` and
`build/tune_repeats.py` simulate the full chain on synthetic hand motion and
report rest wander, lag, overshoot and settle times.

## Dev quickstart

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe mediapipe opencv-python pillow \
    pywebview pyinstaller pygrabber comtypes sounddevice
python -m handjob.main            # app window
python -m handjob.main --dev      # same UI in a browser (mock data)
python -m handjob.main --selftest # model loads?
python -m handjob.main --probe    # camera + overlay + SendInput end-to-end check
python -m tests.test_handjob --full
```

## Build & installer

```bash
bash build_installer.sh
# -> dist/HandJob3000/  +  dist-installer/HandJob3000-Setup-<ver>.exe
```

Requires Inno Setup 6 (`ISCC.exe`); falls back to a 7z SFX if missing.

## Layout

```
handjob/
  main.py           entry point + pywebview API + --selftest/--probe modes
  engine.py         camera → HandLandmarker → cursor pipeline (one thread)
  motion.py         CursorMotion: 144 Hz emitter, interpolation, prediction, hold
  lmsmooth.py       landmark stabilizer (adaptive 1€ + spike gate + palm guard)
  click_refiner.py  pinch → click/drag state machine
  gestures.py       pose classifier, pinch logic, travel mapping (pure functions)
  hand3d.py         3D pinch metric, pose debounce, edge hold, telemetry
  overlay.py        layered click-through cursor overlay
  input_win32.py    SendInput mouse (absolute moves, wheel, buttons)
  settings.py       settings.json beside the exe, clamping + atomic save
ui/index.html       control UI (single file; pywebview bridge + mock fallback)
tests/              python -m tests.test_handjob [--full]
```

Deeper detail in [ARCHITECTURE.md](ARCHITECTURE.md).

## Requirements

- Windows 10/11 (x64) and a webcam. A directly connected camera is smoothest;
  virtual cameras work but add a hop.
- CPU-only by design: MediaPipe's Windows Python build has no GPU delegate;
  the app processes at 480p by default to keep load low.

## License

MIT — see [LICENSE](LICENSE).
