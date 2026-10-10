# HandJob3000 — debugging guide

Everything needed to answer one question: **"is it the camera or the app?"** — and
then to dig into whichever side is at fault. All paths are relative to the app
repo (`Desktop\HandJob3000`); the *installed* app lives in
`%LOCALAPPDATA%\Programs\HandJob3000` and keeps its state (log, settings) right
next to its exe.

---

## 1. The pipeline (what happens to every camera frame)

```
 camera driver ──read()──►  _CamReader thread            ┌─ dup gate: same image? drop (paced)
 (MSMF/DShow)     (own thread: a blocked driver        ──┤
                   can never freeze the engine)           └─ new image? ──► guardar sig, process:
                                                              downscale → flip → RGB
                                                              → HandLandmarker (ONNX-DML / mediapipe)
                                                              → landmark filter (lmsmooth)
                                                              → pose/pinch (hand3d, click_refiner)
                                                              → CursorMotion.ingest
 CursorMotion emitter thread ── 144 Hz ──► OS cursor (SetInput) + overlay orb
```

- **Engine thread** — one loop: consume a frame from the reader → duplicate gate →
  inference → hand logic → feed the motion engine. `handjob/engine.py` `_run()`.
- **Reader thread** (`HJ3-CamReader`) — owns the VideoCapture; the engine never
  calls `read()` directly, so a wedged driver surfaces as a timeout, not a hang.
- **Dup gate** — virtual cameras (Camo/Broadcast/OBS) *repeat* frames whenever
  their source has nothing new; repeats are dropped so all timing/velocity
  estimates stay honest. `_is_dup_sig()` / `SIG_EPS` in `engine.py`.
- **Emitter thread** — `handjob/motion.py`; turns camera-rate samples into a
  144 Hz interpolated/predicted cursor stream. The overlay mirrors it.

## 2. The two camera metrics (learn these, they answer most questions)

Every read gets a cheap 16×16 grayscale signature (`_frame_sig`). Two rates are
computed from the last ~2 s of reads (`_measure_unique_fps`):

| Metric | Meaning | Where |
|---|---|---|
| **reads/s** | how often the driver ANSWERS a read | `bus.cam_reads` |
| **unique/s** | how often the image actually CHANGED (16×16 mean-abs-diff > 0.35) | `bus.cam_unique` |

**A camera can answer at 60 reads/s while sending one still image** — that is
exactly what a paused/standby virtual camera does, and what Camo was doing on
2026-10-10 (`150 frames in 2.48 s = 60.4 reads/s, 149/149 pairs bit-identical`).
The camera's own UI showing "60 fps" only means the driver answers.

Thresholds (all in `engine.py`):

| Constant | Value | Job |
|---|---|---|
| `SIG_EPS` | 0.35 | ≤ this diff = "same frame" (gate + unique rate) |
| `CAMERA_MIN_FPS` | 12 | below = "trickle" → revisit camera mode |
| `FROZEN_UNIQUE_FPS` | 2 | below, twice in a row (~14 s) = frozen → cursor halts + error |

## 3. Watchdogs (each one, what it does, its log line)

| Watchdog | Trigger | Action | Log line |
|---|---|---|---|
| Read stall | no frames at all for `CAMERA_STALL_S` (4 s) | abandon reader, reopen (bounded) | `no frames for X.Xs — reopening (stall N/3)` |
| Delivered rate | < 12 fps for one window (<5 fps) or two windows | reopen with full mode ladder, max once / 90 s | `delivered rate X.X fps — reopening camera to re-measure` |
| Unique rate | unique < 45 % of reads twice | reopen once per camera | `camera repeats frames (X unique of Y reads/s) — reopening once` |
| Frozen source | unique ≤ 2 ×2 (~14 s) | halt cursor + error message | `camera frozen: X unique of Y reads/s — halting cursor` |
| Dup gate | same image as last processed | drop frame, pace to target fps | (no log) |
| Black frames | mean < 2 for ~10 s | warning only | `camera black-frame watchdog tripped` |

Detection diagnosis (which side is broken):

- **reads ≈ 0** → the driver stopped answering: cable/standby/busy driver. Reopen happens automatically.
- **reads ≥ 30 but unique ≈ 0** → the CAMERA is sending a still image (paused
  vcam / disconnected phone / dead source app). The camera UI may still say 60 fps.
- **reads ≈ unique ≈ 15–60** → live camera; smoothness then depends on lighting and motion.

## 4. Diagnostic tools (all in `build/`, all safe: no cursor movement)

Run any of these **as the logged-in user** — the agent session cannot see the
real desktop/camera. Each has a `.cmd` (the actual probe) plus a
`*_run_as_user.ps1` (schtasks wrapper that runs it in your interactive session
and prints the output file):

```powershell
powershell -ExecutionPolicy Bypass -File build\<tool>_run_as_user.ps1
```

| Tool | Answers |
|---|---|
| `cam_truth_probe` | **What is my camera actually sending?** reads/s, unique metric, bit-identical pairs, saves 3 PNGs of the feed so you can SEE it. |
| `cam_probe_safe` | Can cameras 0 and 1 be opened at all, and at what rate? (hang-proof) |
| `real_cam_engine_check` | Runs the REAL engine for 20 s: frames processed, backend, errors — the end-to-end liveness check. |
| `cam_diag` | Per-camera: reads vs unique vs device timestamps (which camera is a repeater). |
| app `--probe` (via `probe3000_run_as_user.ps1`) | Full hardware chain: model load, camera open, SendInput, overlay pixels, engine loop + duplicate-feed survival. |
| app `--selftest` | Model + backend load only (`MODEL_LOAD_OK` / `BACKEND <name>`). |

Frozen app hangs (no logs at all): dump the live process's Python stacks —

```bash
.venv/Scripts/py-spy.exe dump --pid <pid>     # uv pip install py-spy if missing
```

That prints the exact stuck frame (this found the 56-year `sleep()` and the
`join()` crash). `tasklist | findstr HandJob3000` for the pid.

## 5. Log cheat-sheet (`%LOCALAPPDATA%\Programs\HandJob3000\handjob.log`)

| Line | Meaning |
|---|---|
| `inference backend: onnx (DmlExecutionProvider+CPUExecutionProvider)` | GPU engine active |
| `inference backend: mediapipe` | CPU engine (fallback or forced) |
| `camera N: using saved mode WxH` | fast path: cached mode from a previous run |
| `camera N open, engine loop running` | camera ready |
| `first frame captured WxH` | first delivered frame |
| `beat frames=N fps=X lat=Yms` | every 5 s of processing: N unique frames processed, Y = per-frame time (inference included) |
| `camera unique-frame rate U of R reads/s` | the two metrics (§2) |
| `setting …` | UI change applied |
| `engine crashed: …` | engine thread died — report this line |

## 6. "Camera or app?" — the 60-second decision tree

1. `cam_truth_probe` (as user) →
   - **all pairs bit-identical** → CAMERA side: unpause / reconnect the source app
     (Camo Studio pause button, NVIDIA Broadcast source, OBS), or choose a
     directly connected camera. Nothing to fix in the app.
   - **pixel diffs ≥ 1.0 on ≥ 20 frames/s** → live video; any remaining
     complaint is app-side → continue.
2. App-side: `--probe` (all stages green?), then `real_cam_engine_check`
   (frames processed > 10 in 20 s?), then check the log for `beat` fps vs
   `lat` (lat ≈ per-frame ms: ~5 ms on GPU, ~10 ms CPU).
3. Hang with quiet log → `py-spy dump`.
4. Performance/tuning questions → `build/tune_chain.py` (cursor smoothness) and
   `build/tune_repeats.py` (repeating-camera behavior) — synthetic, no camera needed.

## 7. State & where things live

| Path | What |
|---|---|
| `%LOCALAPPDATA%\Programs\HandJob3000\handjob.log` | log (also from the UI: "Open log") |
| `…\settings.json` | all settings incl. `backend`, `cam_mode_cache` (per-camera last-good mode), `camera_index` |
| `…\models\` | imported custom `.task` hand models |
| `handjob/assets/hand_onnx/*.onnx` | the GPU-engine models (converted from the official MediaPipe weights) |

## 8. Code map (what to read for what)

| File | Contents |
|---|---|
| `handjob/engine.py` | camera open ladder + probe, `_CamReader`, dup gate, watchdogs, main loop, backend selection, backends: `_open_camera`, `_measure_unique_fps`, `_is_dup_sig`, `_frozen_cam_state`, `_stall_decision` |
| `handjob/motion.py` | 144 Hz emitter: interpolation, prediction, rest-hold, snap/halt |
| `handjob/lmsmooth.py` | landmark 1€ filter + spike gate + palm guard |
| `handjob/click_refiner.py` | pinch → click/drag state machine |
| `handjob/hand3d.py` | 3D pinch metric, pose debounce, edge hold, telemetry |
| `handjob/hand_onnx.py` | ONNX/DirectML engine (palm detect + landmark crop/port) |
| `handjob/overlay.py`, `main.py`, `ui/index.html` | cursor overlay, UI bridge, control UI |
| `ARCHITECTURE.md` | full per-version history of every fix with causes and measurements |

Build/verify chain for changes: `py_compile` → `python -m tests.test_handjob`
(69 tests) → `bash build_installer.sh` (frozen selftest inside) →
`build/probe3000_run_as_user.ps1` (frozen probe).
