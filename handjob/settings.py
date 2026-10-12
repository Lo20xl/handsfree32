"""Settings: defaults, clamping, load/save (settings.json beside the exe).

Thread-safe: UI thread and engine thread both touch this.
"""
import json
import logging
import os
import threading

from .paths import CONFIG_PATH

log = logging.getLogger("handjob.settings")

DEFAULTS = {
    "camera_index": 0,
    "sensitivity": 0.60,      # 0.10-1.00; higher = less hand travel needed
    "smoothing": 0.55,        # 0.00-0.95; higher = steadier cursor, slight lag
    "click_threshold": 0.28,  # 3D pinch enter ratio (touch ~0.15-0.25, apart 0.6+)
    "prediction_ms": 45.0,    # 0-120; cursor look-ahead that hides camera latency
    "reanchor": True,         # hand takes over the cursor where it is (no jump on engage)
    "drag_px": 12.0,          # 6-30; how far a held pinch moves before it becomes a drag
    "hold_px": 2.5,           # 0-8; rest-hold backlash radius (px). Still hand = rock-steady
                              # cursor; fades to 0 above ~60 px/s so motion has no lag. 0 = off
    "scroll_speed": 1.00,     # 0.25-3.00 multiplier
    "scroll_deadzone": 0.003, # 0.001-0.010; hand wobble below this never scrolls
    "invert_scroll": False,
    "cursor_style": "sky",    # sky | glow | system
    "trail": True,
    "sparkles": True,         # star particles while dragging
    "preview_mode": "wireframe",  # wireframe | camera | off
    "capture_height": 480,    # 480 | 720 | 1080 — processing size (capture stays native)
    "capture_fps": 60,        # 30 | 60 — camera + engine pacing target
    "max_hands": 1,           # 1 | 2 — each extra hand costs ~7 ms/frame of inference
    "edge_margin": 0.04,      # 0.00-0.12; cursor holds position inside this frame margin
    # model selection: "" = bundled hand_landmarker.task; anything else = a
    # MediaPipe .task file imported into models/ beside the app
    "model_file": "",
    # inference runtime: auto = ONNX-Runtime/DirectML GPU when available
    # (falls back to MediaPipe CPU), onnx = GPU only-path, mediapipe = CPU
    "backend": "auto",
    # camera-index -> [w, h] last measured-good mode (skips the startup ladder)
    "cam_mode_cache": {},
    # experimental sonar sensing (speaker+mic Doppler) — sensing only, no control
    "sonar_enabled": False,
    "sonar_in_device": -1,    # sounddevice index; -1 = system default input
    "sonar_out_device": -1,   # sounddevice index; -1 = system default output
    "sonar_tone": 19000,      # 17000 | 19000 | 21000 Hz carrier (inaudible to most adults)
    "start_enabled": False,   # start controlling as soon as the app opens
}

RANGES = {
    "camera_index": (0, 15),
    "sensitivity": (0.10, 1.00),
    "smoothing": (0.00, 0.95),
    "click_threshold": (0.15, 0.50),
    "prediction_ms": (0.0, 120.0),
    "drag_px": (6.0, 30.0),
    "scroll_speed": (0.25, 3.00),
    "scroll_deadzone": (0.001, 0.010),
    "edge_margin": (0.0, 0.12),
    "sonar_in_device": (-1, 63),
    "sonar_out_device": (-1, 63),
}
BOOL_KEYS = {"invert_scroll", "trail", "sparkles", "start_enabled", "reanchor", "sonar_enabled"}
CHOICES = {"cursor_style": ("sky", "glow", "system"),
           "preview_mode": ("wireframe", "camera", "off"),
           "backend": ("auto", "onnx", "mediapipe"),
           "capture_height": (480, 720, 1080),
           "capture_fps": (30, 60),
           "max_hands": (1, 2),
           "sonar_tone": (17000, 19000, 21000)}

_lock = threading.Lock()
# Serialises the read-snapshot -> write -> replace critical section. Two
# writers (UI thread on every slider tick, engine thread for cam_mode_cache)
# used to interleave: A snapshots, B snapshots+B commits, B replaces, A
# replaces -> B's change silently lost. A shared .tmp name made it worse
# (both wrote the same temp file). Unique tmp + this lock = no lost update.
_save_lock = threading.Lock()
_data = dict(DEFAULTS)


def _clamp(key, value):
    if key == "model_file":
        return str(value or "").strip()
    if key in RANGES:
        lo, hi = RANGES[key]
        try:
            return min(hi, max(lo, float(value)))
        except (TypeError, ValueError):
            return DEFAULTS[key]
    if key in BOOL_KEYS:
        return value in (True, 1, "1", "true", "True", "on")
    if key in CHOICES:
        return value if value in CHOICES[key] else DEFAULTS[key]
    return value


def load(path=CONFIG_PATH):
    global _data
    try:
        with open(path, "r", encoding="utf-8") as f:
            disk = json.load(f)
    except FileNotFoundError:
        disk = {}
    except Exception as e:
        log.warning("settings unreadable (%s) — using defaults", e)
        disk = {}
    with _lock:
        merged = dict(DEFAULTS)
        for k, v in (disk or {}).items():
            if k in DEFAULTS:
                merged[k] = _clamp(k, v)
        _data = merged
        return dict(_data)


def get(key=None):
    with _lock:
        return dict(_data) if key is None else _data.get(key)


def set(key, value):  # noqa: A001 - builder's choice, small API
    with _lock:
        if key in DEFAULTS:
            _data[key] = _clamp(key, value)
        snap = dict(_data)
    save()
    return snap


def reset():
    global _data
    with _lock:
        _data = dict(DEFAULTS)
        snap = dict(_data)
    save()
    return snap


def save(path=CONFIG_PATH):
    """Atomic write. `_save_lock` is held across snapshot+replace so concurrent
    callers can never interleave into a lost update; the tmp name carries the
    pid/thread so a failed write can never clobber another writer's temp file."""
    with _save_lock:
        with _lock:
            snap = dict(_data)
        tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snap, f, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            log.warning("settings save failed: %s", e)
            try:
                os.unlink(tmp)
            except OSError:
                pass
