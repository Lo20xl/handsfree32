# HandJob3000 — full code logic & workflow (v2.3.0)

Everything below matches the actual code as shipped in 2.3.0. Line numbers are approximate anchors, not gospel.

---

## 0. Bird's eye

```
camera frame ──► engine thread ──► MediaPipe landmarks ──► stabilizer ──► pose/pinch logic
                     │                                                          │
                     │  (12 fps preview JPEG for the UI)                        ▼
                     │                                          CursorMotion ingest (144 Hz emitter) ──► OS cursor
                     ▼                                                          │
              overlay thread (30 fps layered window: orb/trail/sparkles) ◄─────┘
```

- **`handjob/engine.py`** — the core. One background thread owns camera + model + logic.
- **`handjob/motion.py`** — turns 10–60 Hz hand samples into a smooth 144 Hz cursor stream.
- **`handjob/lmsmooth.py`** — landmark-level filter (kills jitter + tracker spikes before pose/pinch read anything).
- **`handjob/click_refiner.py`** — pinch → click/drag state machine.
- **`handjob/gestures.py`** — pure functions: pose classification, finger flags, screen mapping, scroll accumulation.
- **`handjob/hand3d.py`** — 3D pinch metric, pose debounce, edge hold, telemetry.
- **`handjob/overlay.py`** — the sky-orb cursor window (click-through, layered).
- **`handjob/sonar.py`** — experimental speaker+mic Doppler sensing (never drives the cursor).
- **`handjob/main.py`** — pywebview UI bridge (`Api` class) + `--probe` / `--selftest`.
- **`ui/index.html`** — the whole UI (single file; talks to `Api` via `window.pywebview.api`).

---

## 1. Process & threads

| Thread | Owner | Job | Rate |
|---|---|---|---|
| Main | pywebview | UI window + `Api` methods (`get_state`, `set_setting`, …) | on demand |
| Engine | `Engine._run()` | camera → landmarks → stabilize → pose/pinch → ingest/halt | paced to 30 or 60 fps (`capture_fps`) |
| Motion emitter | `CursorMotion` | ALL absolute cursor moves (`SetCursorPos`) — interpolated + predicted | 144 Hz |
| Overlay | `Overlay.run()` | layered click-through window, orb/trail/sparkles | 30 fps |
| Sonar (optional) | `Sonar._run()` | FFT of mic blocks → motion/velocity diagnostics | ~30 Hz |

- Single-instance mutex `HandJob3000_SingleInstance` (`main.py`).
- Panic stop: `Ctrl+Alt+H` — checked per engine frame via `GetAsyncKeyState` (`Engine._estop_pressed`).
- The engine thread is the ONLY writer of "truth" (bus state); the overlay and UI only read.

---

## 2. Per-frame pipeline (engine `_run` loop — order matters)

1. **Camera switch request** — UI can request another camera index; handled at frame top.
2. **`capture.read()`** — plus two watchdogs:
   - *stall*: no frames for 2 s → reopen camera (`CAMERA_STALL_S`);
   - *black frames*: mean < 2.0 for ~10 s → user warning (lens cover / privacy setting).
3. **Delivered-rate watchdog** (2.3) — every 3 s, measured processed-fps; < 12 fps while not on the lowest rung → reopen once so the resolution ladder re-measures.
4. **`cfg = settings.get()`** — live settings, read fresh every frame (sliders apply instantly).
5. **Prediction update** — `_effective_prediction(slider_ms, dt)` = `max(slider, 1.3 × camera interval)`; at 30+ fps the slider wins, at ~10 fps it scales to ~130 ms.
6. **Rate / hand-count changes** → reopen camera / reload the landmarker with new `num_hands`.
7. **Software downscale** — full native frame → `capture_height` (default 480) with `INTER_AREA`; flip (selfie view); BGR→RGB. (The camera always opens at its native mode — no driver crops.)
8. **`landmarker.detect_for_video(rgb, ts)`** — MediaPipe HandLandmarker (VIDEO mode, 1 hand default). Gives 21 image landmarks + 21 world landmarks (metres).
9. **Primary-hand select** — sticky: first hand seen keeps control; matched by palm-center distance; 0.7 s grace after loss (`gestures.PrimaryHandSelector`).
10. **LandmarkStabilizer** (`lmsmooth.py`) — the anti-jitter core, applied to both image + world landmarks:
    - adaptive 1€ filter per landmark (heavy at rest, ~raw while moving);
    - spike gate: single-frame jump > budget (0.25 palm + 2.5 × speed × dt) → clamped (teleports die here);
    - palm-scale guard: palm length jump > 40 % in one frame → frame rejected (z-glitch).
11. **`_process_hand(...)`** — the brain:
    - **Pinch**: `PinchMeter3D.update(world, lms)` → smoothed l/r ratios (3D preferred; 2D veto keeps a hovering thumb from clicking).
    - **Pose**: `classify_pose(lms, pinching)` → `point | scroll | idle`, then `PoseTracker` debounce (2 frames + dwell 60 ms enter / 100 ms leave / 300 ms leave-while-holding).
    - **Edge hold**: inside the frame margin (4 %) the last stable aim point keeps driving (hysteresis band).
    - **Mapping**: `TravelMapper.to_screen` — pick-up mapping (`reanchor`) or absolute; sensitivity.
    - **Clicks**: `ClickRefiner.observe(raw_x, raw_y)`; `update_left/right(ratio)` → events. Cursor target = anchor (while pinch) / drag ramp / live position.
    - **Feed motion**: pose `point` & armed → `motion.ingest(now, x, y)`; anything else → `motion.halt()` (clutch: freeze in place).
    - **Events**: `snap(anchor)` runs BEFORE `wi.button` down / right-click so the press lands exactly on the aim point; scroll → `wi.wheel(notches)`.
    - **Bus updates**: `found/dim/armed/style/position`, trail, drag sparkles.
12. **Preview encode** — wireframe/camera/off, max ~12 fps (throttled); JPEG bytes to `bus.set_preview` for the UI.
13. **Sonar sync** — start/stop/restart on settings change; never in the cursor path.
14. **Pacing** — sleep to hit the 30/60 fps budget.

---

## 3. CursorMotion (motion.py) — how smoothness actually happens

- Ring of recent samples (0.2 s). Each `ingest()` adds a sample; the **emitter thread** runs at 144 Hz and on every tick computes a target = smoothed position + velocity × prediction lead (deceleration-aware extrapolation, soft-capped at ~40 px × scale).
- Between camera samples the emitter keeps moving the cursor toward the predicted target — **this is the interpolation**; it never waits for the next frame.
- `snap(x,y)` = teleport + emit with zero velocity (clicks). `halt()` = freeze in place (no run-on/retract after stop).
- If the next sample is overdue (> 1.35 × interval + 12 ms) the prediction retracts — cursor settles instead of flying off.
- Deadzone is a whole-pixel check in `_emit` — the OS cursor never receives sub-pixel churn.
- All output goes through `_emit_cursor` → `input_win32.move_absolute` — one choke point, one thread.

## 4. FPS semantics — "why do I see 10 fps?" (2.3 measured facts)

| Number | Where | Meaning |
|---|---|---|
| **Preview ~12 fps** | app window wireframe | **by design** (`PREVIEW_MIN_INTERVAL = 0.08`) — cosmetic only, does NOT reflect tracking rate |
| `bus.fps` | UI "fps" stat | frames *processed* per second (15-frame rolling window) — the real tracking rate |
| `infer_ms` | UI stats | MediaPipe inference time per frame (~10–14 ms on this desktop) |
| emitter 144 Hz | cursor movement | interpolated stream; smoothness ≠ camera fps |

Measured on this desktop (RTX 5070, 2.3.0): camera delivers **30.5 fps** at 720p; full pipeline end-to-end **50.7 fps** at the 60 fps target; inference median **13.4 ms**. If the UI fps stat reads ~10 on a laptop: that's the camera's delivered rate (the 2.3 ladder + watchdog tries to fix it). The preview will always *look* 12 fps even when everything is perfect.

---

## 5. Click / drag state machine (click_refiner.py)

- Pinch ratio below threshold for 2 confirm frames → **left down**; release ratio 1.25× for hysteresis.
- **Anchor**: the click lands at the position from ~0.12 s lookback (wobble-free), cursor frozen from pinch start.
- **Drag**: unlock radius adaptive (shaky hand → bigger); held pinch turns into drag after a few px; eased ramp from anchor into the hand (no jump). Blips don't drop a drag.
- **Double-click**: quick re-pinch within a short window → Windows double-click (same anchor).
- Right click: thumb+ring, 0.25 s cooldown, single fire per pinch.
- Non-point pose → `release_all` (buttons up, lock cleared).

## 6. UI ↔ backend protocol

- `ui/index.html` calls `window.pywebview.api.<method>`; methods live in `main.py` `Api`:
  `get_state` (700 ms poll), `set_setting`, `preview` (looped), `get_telemetry`, `sonar_devices`, `set_control`, `refresh_app`, `reset_settings`, `open_log`.
- Settings flow: slider → `set_setting` → `settings.set` (clamped) → persisted `settings.json` → engine picks it up next frame.
- UI works in a plain browser too (mock `api()` object) — useful for UI-only work.

## 7. Settings (settings.py)

- `DEFAULTS` (values), `RANGES` (clamps), `CHOICES` (enums), `BOOL_KEYS` — one table, validated on every write.
- Stored as JSON next to the exe (frozen) / repo root (dev). New keys are additive; unknown keys ignored.

## 8. Verification chain (never skip)

1. `py_compile` changed files.
2. `python -m tests.test_handjob [--full]` — 44 tests (--full adds real-inference sample-image test).
3. Dev probe as the logged-in user (`build/dev_probe_run_as_user.ps1`) — overlay pixels + `PROBE OK`.
4. `bash build_installer.sh` → PyInstaller onedir → strip CUDA/DirectML → **frozen `--selftest`** (`MODEL_LOAD_OK`, `SONAR_STACK_OK`) → Inno Setup installer.
5. Frozen probe (`build/probe3000_run_as_user.ps1`) — `PROBE OK`, overlay ≥ ~1000 orb px, fps/latency lines.
6. `bash build/deliver.sh` → Downloads (exe + zip + README) → Drive upload (relay chain, md5-verified).

## 9. Where the next features will slot in

- **Model picker / custom imports**: `Engine._load_model()` currently reads fixed `MODEL_NAME`. Plan: setting `model_file` (bundled `hand_landmarker.task` + imported `.task` files in a `models/` dir next to the exe) → `_load_model` resolves it; the existing reload path (hand-count change) gets reused for live switching; UI card with a file picker for imports. Custom files validated by a test-load before being accepted.
- **Interpolation control** (`fps < threshold` + amount): slots into `_effective_prediction` + `motion.configure` — an `interp_min_fps` (default 25) gate and an `interp_amount` gain applied when the measured rate is below it. The 144 Hz emitter already interpolates; this adds explicit user control over how aggressively.

## 10. Known constraints

- **GPU**: MediaPipe's Windows Python build has GPU disabled at compile time (`Delegate.GPU` → "GPU processing is disabled in build flags"). CPU-only is by design; the app keeps load low instead (1 hand, 480p processing).
- **MediaPipe Python cannot load alternative pose models** (e.g. ONNX RTMPose) — the Tasks API only accepts MediaPipe `.task` bundles. A model picker can offer: bundled hand_landmarker, any compatible `.task` file (e.g. gesture_recognizer bundles, older/newer hand models), and possibly community-trained bundles — not arbitrary model formats.

---

## 11. 2.4.1 — smoothness pass (cursor / ring / preview)

Symptoms: cursor + highlight ring jittery, "polling stuck at ~10 fps".

| Cause found | Fix |
|---|---|
| **Overlay redrew + re-uploaded a desktop-sized bitmap every frame** (14 ms CPU @1080p, 47 ms @4K, plus a full-surface DWM composite). The ring — which *is* the cursor when the OS arrow is hidden — ran at 10–30 fps and was sampled at uneven moments. | `overlay.py`: one DIB allocated once; each frame renders only the sprite's bounding box (`view_bounds`), premultiplies **straight into that DIB sub-rectangle** (`_premultiply_into`), and calls `UpdateLayeredWindow` with matching `pptSrc/psize/pptDst`. ~1 ms/frame at any resolution (3.5 ms with a long trail). Loop is woken by the emitter (`bus.visual_event`) so the ring moves in lock-step with the 144 Hz cursor. |
| Ring edges were hard (non-AA) → pixel crawl while moving | 2× supersampled render (`render_frame(..., ss=2)`, `_SSDraw` proxy), automatically off when the sprite is large. |
| Trail was fed at camera rate (30 Hz) → stair-stepped tail behind a smooth ring | Trail points now come from the emitter (`_emit_cursor`, ≥10 ms / ≥3 px apart), cap 48. |
| Frame timestamps were taken **after inference** (10–30 ms of random jitter in every dt → velocity ripple in landmark filters, pose dwell, cursor prediction) | `engine._run`: `t_read` stamped the instant `capture.read()` returns; `now = t_read`. Test shows ~2× lower cursor jerk at 30 fps. |
| UI preview loop slept 110 ms between polls (hard ~9 fps ceiling, looks like tracking at 10 fps) | `Api.preview(last_seq)` long-polls (`bus.wait_preview`); JS loop has no sleep and never re-downloads an unchanged frame. |
| Emitter / overlay threads starved by inference + UI threads | `sys.setswitchinterval(0.001)`; emitter priority HIGHEST, overlay ABOVE_NORMAL (`input_win32.boost_thread_priority`). |
| Camera itself delivering ~10 new frames/s in dim light (webcam auto-exposure) | Warning in the UI when unique frames/s < 18; new **Camera driver settings…** button (`CAP_PROP_SETTINGS`) to turn off low-light compensation / dynamic frame rate. |

---

## 12. 2.4.4 — repeat-frame gate (virtual cams)

Symptoms again: jitter / lurching / delay, reported while on a virtual camera.
The user's log: `camera unique-frame rate 8.5 of 54.7 reads/s`.

| Cause found | Fix |
|---|---|
| Virtual cams (Camo / NVIDIA Broadcast / OBS) answer every read by repeating the last frame, and the engine ran inference + fed motion on EVERY read. The repeats pinned the velocity estimate to ~0; when a genuinely new frame arrived it carried 60+ ms of hand motion in an 18 ms dt → velocity ~3.7× too high → the 1€ cutoff boost passed it almost unfiltered → the cursor lurched on each update and stalled in between. | `engine._run`: **duplicate-frame gate before inference** (`_is_dup_sig`, the same 16×16 signature metric + `SIG_EPS` threshold the unique-frame watchdog uses; compare against the last PROCESSED frame). Repeats `continue` the loop (paced). Only new frames advance inference / landmark filter / refiner / motion, so every dt and velocity is honest and the emitter interpolates across correctly-measured gaps. Also skips ~80% of CPU on such cameras. Only captures the engine opened itself (`_dedupe`); probe/synthetic feeds are never gated. |
| The repeat watchdog reopened the camera every ~2 min (multi-second blackout + re-probe) — useless for a chronic repeater, and a visible "delay" in itself. | Demoted to **one chance per camera** (re-armed on a manual camera switch); chronic repeaters are handled by the gate. The <18-unique warning now distinguishes virtual-cam repeats (high read rate → "check the source app") from dim-light/auto-exposure advice. |
| `delivered rate` watchdog counted processed frames — after the gate it would have measured the unique rate and misfired. | Counts raw reads (`_read_count`); `bus.frames` counts processed (unique) frames. |

Harness numbers (`build/tune_repeats.py`: 55 reads/s + 15 unique/s synthetic
camera, 200 px/s glide, 3 seeds): step-CV **2.49 → 1.11** (2.2× steadier
per-tick advance), RMSE-optimal lag **93 → 79 ms**, RMSE **9.0 → 6.8 px**.

---

## 13. 2.4.5 — blocking-read stall guard (the "app froze / cameras look broken" fix)

Symptom: the app opened a camera and then silently froze — preview stuck, no
tracking, but the window still responsive and no error shown. Found live twice
in one session: after opening camera 0 (Camo, mid-restart) and after switching
to camera 1 (NVIDIA Broadcast with a wedged driver — VCAMDS spamming
"NvMxnCltShmConsumer Init Failed. Err: -610"). Root cause: the engine loop
called `capture.read()` directly, and a virtual-camera driver in a bad state
accepts the open, delivers one frame, then **never returns from the next
read()**. The engine thread sat inside the driver call — where no in-loop
watchdog can run — so stall detection, the unique-frame watchdog, beats and
error surfacing all stayed silent, forever. Closing the app could hang too
(release() on a wedged handle).

| Cause found | Fix |
|---|---|
| `capture.read()` on the engine thread can block forever in a wedged driver | New `_CamReader` thread owns the capture: it reads in a loop into a single newest-wins slot (paced to 1.5× target fps so instant-answering vcams can't spin a core). The engine loop waits on `get(seq, timeout)` — a blocked read now surfaces as a **timeout**. The reader is a daemon: an abandoned stuck read can never block app exit. |
| Nothing could recover from a silent feed | **Read-stall watchdog**: NO frames for `CAMERA_STALL_S` (4 s) → abandon the stuck reader, reopen bounded (`_open_bounded` — the open itself can hang in the driver; daemon + 12 s deadline), keep going. `_stall_decision` gives up after `CAMERA_STALL_REOPENS` (3) consecutive stalls with a clear UI error ("camera keeps going silent — the driver looks stuck…"); a healthy 60 s re-arms the budget. |
| App exit could block on `release()` of a wedged camera | `cleanup()` never releases inline; the reader owns release (runs in its own thread), reader-less captures release in a daemon. |
| Camera-switch failure left `capture=None` and relied on read() to raise | Switch path now uses `_stop_reader` + `_open_bounded`; a failed switch is picked up by the stall watchdog. |

Tests: `test_cam_reader_times_out_not_hangs`, `test_engine_read_stall_recovers`
(full `_run` with a capture that blocks forever after frame 1 — the engine must
abandon it, reopen and keep processing; the log shows "no frames for 0.8s —
reopening (stall 1/3)"), `test_stall_decision_policy`,
`test_engine_read_stall_wiring`.

---

## 14. 2.5.0 — GPU inference backend (ONNX Runtime + DirectML)

MediaPipe's Windows pip build cannot use the GPU (its GPU path is compiled
out: "GPU processing is disabled in build flags" — re-verified on mediapipe
1.1.0), so the landmark stage ran ~7-10 ms on the CPU. 2.5.0 adds a second
backend that reimplements the same two-stage hand pipeline on ONNX Runtime with
the DirectML execution provider (any DX12 GPU):

| Piece | What |
|---|---|
| Models | Converted the official weights with `tflite2onnx` (palm_detection_full + hand_landmark_lite → `handjob/assets/hand_onnx/*.onnx`; ~8 MB). Two converter bugs fixed locally (rank-vs-layout skips) and palm's SE-block PRelu slopes reshaped (1,1,C)→(1,C,1,1). **Numerics verified identical to the tflite runtime** (max abs diff ≤2e-4 on random and real inputs). |
| `handjob/hand_onnx.py` | The ported pipeline: letterboxed 192 palm input (keep_aspect, zero border) → SSD decode at scale 192 relative to **unit anchors** (`fixed_anchor_size` sets w=h=1.0 — this is NOT the per-layer scale!), **linear** w/h decode (`apply_exponential_on_box_size` defaults false), **weighted NMS** (IoU .3, score-weighted box+kp averaging — MediaPipe's WEIGHTED algorithm), detection letterbox removal → crop per `palm_detection_detection_to_roi` (rotate so wrist kp0 → middle-MCP kp2 is "up", shift_y −0.5, square-long, ×2.6 → 224) → landmark model → inverse crop map. Landmark outputs are **[x,y,z] triples per point** (63 values, stride 3 — reading pairs garbles everything after the wrist). |
| Parity | On MediaPipe's own test images (`thumb_up.jpg`) the backend matches the official expected landmarks **6.1 px mean / 12 px max** (mediapipe itself: 0.1 px). Landmark stage ~0.6 ms on DirectML vs ~7.5 ms CPU (palm ~0.7 ms). |
| Integration | `settings.backend` ("auto" / "onnx" / "mediapipe"), System-card *Inference engine* select, live switch in the engine loop (`_backend_seen` → `_load_model`), `BACKEND` line in `--selftest`, fallback chain onnx → mediapipe on any load error. Custom `.task` models and 2-hand mode always use MediaPipe. |

Known limits of the ONNX backend: palm acquisition can mislock on scenes with
a strong hand-shaped shadow (reproduced on mediapipe's `pointing_up.jpg`,
where the third-party pipeline finds the hand but ours locks the shadow
region) — the landmark stage itself is exact once locked; multi-hand and
custom models use the CPU engine. Default `backend: "auto"` keeps the
verified CPU path one dropdown away.
