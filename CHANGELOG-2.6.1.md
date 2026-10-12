# 2.6.1 — merge: 2.6.0 architecture + the ONNX inference backend

2.6.0 was built on an older base and lost the ONNX/DirectML inference backend in
the process. This restores it on top of the 2.6.0 architecture.

**Restored — `settings.backend` = `auto` | `onnx` | `mediapipe`**

- `handjob/hand_onnx.py` + `handjob/assets/hand_onnx/{palm_detection_full,hand_landmark_lite}.onnx`
  back in the tree and wired into `Engine._load_model`.
- New **Inference backend** select in the System card; switches live (no restart).
- Measured on this machine (thumb_up.jpg, 60-frame mean):

  | backend | ms/frame | hands |
  |---|---|---|
  | MediaPipe | 8.11 | 1 |
  | ONNX / DirectML | **2.89** | 1 |

  Landmark deviation vs MediaPipe ~8 px (wrist/middle-MCP), in line with the
  6.1 px mean parity measured when the backend was first ported.
- Falls back to MediaPipe on its own if onnxruntime is missing or there is no
  DX12 GPU — the app never ends up with no tracker.
- `HandJob3000.spec` now `collect_all('onnxruntime')`; without it the frozen exe
  raises on import and silently degrades.

**Fixed while porting**

- `run_dev_selftest()` never called `settings.load()`, so `--selftest` always
  tested DEFAULTS regardless of what was actually saved. It now prints the real
  `BACKEND` line and honours your saved settings.
- Sensitivity floor 0.10 -> 0.01 (sub-10% aiming).

**Tests**: 70 pass (was 67 pass / 1 fail on the 2.6.0 zip, which shipped no model
assets so its model test could not run). Added `test_onnx_backend_loads_and_falls_back`
(load + forced-degradation) and `test_onnx_inference_gets_raw_bgr_frame`
(the BGR/RGB swap that silently drops palm detection to zero hands).

**Not carried over from the 2.5.x line** (mechanisms 2.6.0 replaced or that were
reverted): `_CamReader` + the duplicate-frame gate + the read-stall watchdogs
(all superseded by `camera.FrameGrabber`'s newest-frame-wins design), `hold_px`
rest-hold backlash, and adaptive gain. The pre-merge test suite is kept at
`tests/test_handjob.2510.bak`.
