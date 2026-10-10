"""HandJob3000 engine: camera -> MediaPipe HandLandmarker -> cursor & clicks.

One background thread owns the camera, the model, the cursor and the overlay
bus. The UI thread only reads stats and toggles flags (thread-safe).

Perf: the camera is asked for its native 1280x720 MJPG mode (one mode webcams
and virtual cams deliver without driver-side cropping), then the frame is
DOWNSCALED in software to the processing size. num_hands defaults to 1: the
landmark model runs once per detected hand, so a second hand costs ~7 ms per
frame — the difference between a 30 Hz and a 60 Hz loop.

2.1: edge hold (EdgeStabilizer) keeps the cursor still while the aim point is
inside the frame margin, where MediaPipe landmarks go noisy; experimental
sonar sensing (`sonar.py`) is supervised here but never drives the cursor.
"""
import base64
import logging
import math
import os
import random
import shutil
import sys
import threading
import time
from collections import deque

import cv2
import numpy as np

from . import gestures as G
from . import input_win32 as wi
from . import settings
from .paths import app_dir, assets_dir
from .motion import CursorMotion
from .click_refiner import ClickRefiner
from .hand3d import PinchMeter3D, PoseTracker, EdgeStabilizer, reanchor, os_cursor_pos, Telemetry
from .lmsmooth import LandmarkStabilizer

MODEL_NAME = "hand_landmarker.task"
CUSTOM_MODELS_DIR = "models"          # imported .task files live here, beside the app
PREVIEW_JPEG_QUALITY = {"jpg": [int(cv2.IMWRITE_JPEG_QUALITY), 55]}
SKY_BGR = (248, 189, 56)
WHITE_BGR = (255, 255, 255)

ENGINE_FPS_FALLBACK = 30     # pacing target when capture_fps is unknown
PREVIEW_MIN_INTERVAL = 0.034  # ~30 fps preview encode — the UI mirrors tracking 1:1
CAMERA_STALL_S = 4.0         # NO frames at all for this long -> the read is stuck
CAMERA_STALL_REOPENS = 3     # consecutive stall reopens before giving up (per ~minute)
CAMERA_OPEN_DEADLINE_S = 12.0  # a wedged driver can hang VideoCapture() itself
CAMERA_MIN_FPS = 12.0        # delivered fps below this = driver trickle mode
FROZEN_UNIQUE_FPS = 2.0      # at/below this the source is frozen, not merely slow
FROZEN_ERR = ("camera frozen — same frame repeating, ~0 new frames/s. Virtual cameras "
              "(NVIDIA Broadcast, Camo, OBS) do this when their source app is closed, "
              "PAUSED, or a phone is disconnected: pick a live camera in the Camera "
              "dropdown or fix the source (unpause / reconnect), then click Refresh app")
SIG_EPS = 0.35                # 16x16 mean-abs diff at/below this = the same frame

# device names that identify a VIRTUAL camera chain (their frame source is a
# separate app/phone we cannot see; "reads/s" then says nothing about liveness)
_VIRTUAL_CAM_HINTS = ("camo", "broadcast", "obs", "virtual", "snap", "manycam",
                      "droidcam", "iriun", "epoccam", "ndi")


def _is_virtual_cam_name(name: str) -> bool:
    n = (name or "").lower()
    return any(h in n for h in _VIRTUAL_CAM_HINTS)


def _is_dup_sig(sig, prev) -> bool:
    """True when `sig` is (within sensor noise) the same frame as `prev`.

    Virtual cams answer every read by repeating the last frame until the source
    produces a new one; feeding those repeats downstream inflates every dt and
    velocity estimate, so they must be dropped before the pipeline."""
    return prev is not None and float(np.abs(sig - prev).mean()) <= SIG_EPS


def _stall_decision(stalls, max_reopens):
    """After `stalls` consecutive no-frame reopen attempts: what next?

    'reopen' while attempts remain, then 'give_up' — same policy style as the
    frozen-camera watchdog. Chronic flappers get a clear error instead of an
    endless reopen loop."""
    return "give_up" if stalls > max_reopens else "reopen"


class _CamReader(threading.Thread):
    """Reads frames from a VideoCapture on its OWN thread so a driver-level
    blocking read() can never wedge the engine loop.

    A virtual-camera driver in a bad state can accept a capture and then never
    return from read() — observed live with the NVIDIA Broadcast chain: the
    engine thread sat in read() forever while the UI stayed up, so the user saw
    a frozen preview and no tracking. The engine instead WAITS here with a
    timeout and can abandon this reader (a read stuck in the driver cannot be
    interrupted; the daemon thread leaks until the driver returns, if ever) and
    open a fresh capture.

    The newest frame wins (single slot): a slow consumer never builds a backlog.
    """

    def __init__(self, cap, max_hz=90.0):
        super().__init__(daemon=True, name="HJ3-CamReader")
        self.cap = cap
        self._min_dt = 1.0 / max(1.0, float(max_hz))
        self._cv = threading.Condition()
        self._slot = None            # (t_read, frame) — newest
        self._seq = 0
        self._fail_since = None      # wall time since the driver started failing reads
        # NOT "_stop": threading.Thread uses self._stop() internally in join()
        # once the thread has finished — an attribute with that name makes any
        # later join() die with "'Event' object is not callable".
        self._abort = threading.Event()

    def run(self):
        cap = self.cap
        while not self._abort.is_set():
            t0 = time.time()
            try:
                ok, frame = cap.read()
            except Exception:
                ok, frame = False, None
            if self._abort.is_set():
                break
            with self._cv:
                if ok:
                    self._fail_since = None
                    self._slot = (time.time(), frame)
                    self._seq += 1
                elif self._fail_since is None:
                    self._fail_since = time.time()
                self._cv.notify_all()
            dt = time.time() - t0
            wait = self._min_dt - dt
            if wait > 0:
                time.sleep(wait)      # a vcam answering instantly must not spin a core
        # best-effort release; this thread may itself be stuck in read() — fine,
        # it is a daemon and the app never waits on it past `_stop_reader`'s join
        try:
            cap.release()
        except Exception:
            pass

    def get(self, last_seq, timeout):
        """Wait for a frame newer than `last_seq`.

        Returns (seq, t_read, frame), or None when nothing arrived in `timeout`
        (frame=None means the driver reported a failed read)."""
        with self._cv:
            self._cv.wait_for(
                lambda: self._seq != last_seq or self._fail_since is not None or self._abort.is_set(),
                timeout=timeout)
            if self._seq != last_seq:
                return self._seq, self._slot[0], self._slot[1]
            if self._fail_since is not None:
                return self._seq, None, None
            return None

    def abandon(self):
        self._abort.set()
        with self._cv:
            self._cv.notify_all()


def _frozen_cam_state(urate, streak):
    """(streak, action) for the frozen-camera watchdog. action: 'error' | 'clear' | 'ok'.

    A live camera always produces new frames — sensor noise alone changes every
    read — so <=FROZEN_UNIQUE_FPS unique frames/s means the source is frozen, not
    dim or slow. Two consecutive checks (~14 s) before erroring: one bad window
    can be a hiccup."""
    if urate is None:
        return streak, "ok"
    if urate < FROZEN_UNIQUE_FPS:
        streak += 1
        return streak, ("error" if streak >= 2 else "ok")
    return 0, ("clear" if streak else "ok")
CAMERA_PROBE_S = 0.6         # seconds of frames read to measure a fresh capture
PRED_MIN_LEAD_S = 1.3        # prediction floor = 1.3 camera intervals


def _effective_prediction(slider_ms, dt) -> float:
    """Prediction to run with: the slider value, but never less than ~1.3
    camera intervals — at 30+ fps this is below the default 45 ms (slider
    wins, unchanged), at ~10 fps feeds it scales to ~130 ms so the emitter
    can interpolate across the whole gap instead of jumping per sample."""
    try:
        v = float(slider_ms or 0.0)
    except (TypeError, ValueError):
        v = 45.0
    return max(v, PRED_MIN_LEAD_S * float(dt) * 1000.0)


# ---------------------------------------------------------------- models ----
def _task_base(name) -> str:
    """Bare filename of a model choice (no path parts)."""
    return os.path.basename(str(name or "").strip())


def _task_path(name) -> str:
    """Absolute path for a model choice: bundled default or an imported file."""
    base = _task_base(name)
    if not base or base == MODEL_NAME:
        return os.path.join(assets_dir(), MODEL_NAME)
    return os.path.join(app_dir(), CUSTOM_MODELS_DIR, base)


def _landmarker_options(path, hands):
    # imported lazily: mediapipe pulls matplotlib (~2 s of startup) and is only
    # needed when the MediaPipe backend actually loads — the ONNX/GPU backend
    # never touches it.
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    return vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=path),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=hands,  # each extra hand runs the landmark model again (~7 ms)
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )


def list_models():
    """[{"file", "label", "custom"}] — bundled default plus every imported .task."""
    out = [{"file": "", "label": "Default (bundled hand_landmarker)", "custom": False}]
    try:
        d = os.path.join(app_dir(), CUSTOM_MODELS_DIR)
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith(".task") and os.path.isfile(os.path.join(d, fn)):
                out.append({"file": fn, "label": fn, "custom": True})
    except FileNotFoundError:
        pass
    except Exception:
        log.exception("listing models failed")
    return out


def validate_model(path) -> bool:
    """Load the file as a hand landmarker to prove it works; raises on failure."""
    from mediapipe.tasks.python import vision
    lm = vision.HandLandmarker.create_from_options(_landmarker_options(path, 1))
    lm.close()
    return True


def import_model(src_path, file_name=None) -> str:
    """Copy an external .task into models/ after test-loading it.

    Returns the stored bare filename. Raises ValueError on an unusable file."""
    src_path = str(src_path or "")
    if not os.path.isfile(src_path):
        raise ValueError("file not found")
    base = _task_base(file_name or src_path)
    if not base.lower().endswith(".task"):
        base = os.path.splitext(base)[0] + ".task"
    if base == MODEL_NAME:
        raise ValueError("that name is reserved for the bundled model")
    try:
        validate_model(src_path)      # test-load BEFORE it touches the disk
    except Exception as e:
        raise ValueError(f"not a usable MediaPipe hand model: {e}") from e
    d = os.path.join(app_dir(), CUSTOM_MODELS_DIR)
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, base)
    if os.path.abspath(src_path) != os.path.abspath(dst):
        shutil.copyfile(src_path, dst)
    return base
CAPTURE_W, CAPTURE_H = 1280, 720  # native 16:9 mode requested from every camera

HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
)

log = logging.getLogger("handjob.engine")


class _FakeCapture:
    """Dev/support mode (HJ3_FAKE_CAM): replays a still image as a camera."""

    def __init__(self, img):
        self._img = img

    def isOpened(self):
        return True

    def read(self):
        return True, self._img.copy()

    def release(self):
        pass


class CursorBus:
    """Producer(engine) -> consumer(overlay) shared cursor/visual state."""

    def __init__(self):
        self.lock = threading.Lock()
        self.overlay_enabled = True     # master switch for the overlay window
        self.position = None            # (x, y) float screen px
        self.armed = False              # is cursor control actually on
        self.style = "sky"
        self.dim = True
        self.press = 0.0                # visuals: click emphasis 0..1
        self.pulse = None               # (x, y, wall_time) click ripple
        self.particles = []             # (x, y, vx, vy, born, kind)
        self.trail = []                 # (x, y, wall_time)
        self.found = False
        self.fps = 0.0
        self.latency_ms = 0.0
        self.frames = 0
        self.error = None
        self.warning = None             # soft warning (e.g. black camera frames)
        self.cam_reads = None           # camera delivered reads/s (unique-frame watchdog)
        self.cam_unique = None          # camera NEW frames/s — what the cursor actually gets
        self.virtual_screen = wi.virtual_screen()
        self.visual_event = threading.Event()   # set whenever the overlay has something new to draw
        self._preview = None
        self._preview_seq = 0
        self._preview_lock = threading.Lock()
        self._preview_cv = threading.Condition(self._preview_lock)

    # -- overlay side --------------------------------------------------------
    def snapshot(self, now=None):
        now = now or time.time()
        with self.lock:
            if self.pulse and now - self.pulse[2] > 0.35:
                self.pulse = None
            self.particles = [p for p in self.particles if now - p[4] < 0.6]
            # 2.3: the orb renders only while a hand is actually detected —
            # no hand, no highlight (the OS cursor is untouched either way)
            show_cursor = self.armed and self.position is not None and self.found
            if not show_cursor and not self.pulse and not self.particles:
                return None
            trail = ([(x, y, now - t) for (x, y, t) in self.trail if now - t < 0.5]
                     if show_cursor else [])
            return dict(
                cursor=(self.position if show_cursor else None),
                style=self.style, dim=self.dim,
                armed=self.armed, press=self.press, pulse=self.pulse,
                particles=list(self.particles), trail=trail,
            )

    # -- engine side ---------------------------------------------------------
    def update_trail(self, x, y, now):
        with self.lock:
            self.trail.append((x, y, now))
            if len(self.trail) > 48:
                self.trail = self.trail[-48:]
        self.visual_event.set()

    def spawn_sparkles(self, x, y, now, n=2):
        with self.lock:
            for _ in range(n):
                ang = random.random() * math.tau
                sp = 60 + random.random() * 90
                self.particles.append(
                    (x, y, math.cos(ang) * sp, math.sin(ang) * sp - 30,
                     now, "star" if random.random() < 0.6 else "dot"))
            if len(self.particles) > 140:
                self.particles = self.particles[-140:]
        self.visual_event.set()

    def set_preview(self, jpg_bytes):
        with self._preview_cv:
            self._preview = jpg_bytes
            self._preview_seq += 1
            self._preview_cv.notify_all()

    def get_preview(self):
        with self._preview_lock:
            blob = self._preview
        if not blob:
            return None
        return "data:image/jpeg;base64," + base64.b64encode(blob).decode("ascii")

    def wait_preview(self, last_seq, timeout=0.06):
        """Long-poll for the UI: block until a preview newer than `last_seq`
        exists (or `timeout`), then return (seq, data-url-or-None). The UI loop
        therefore runs at the preview's real rate with no fixed sleep and never
        re-downloads a frame it already has."""
        with self._preview_cv:
            if self._preview_seq == last_seq:
                self._preview_cv.wait(timeout)
            seq, blob = self._preview_seq, self._preview
        if seq == last_seq or not blob:
            return seq, None
        return seq, "data:image/jpeg;base64," + base64.b64encode(blob).decode("ascii")


class Engine(threading.Thread):
    def __init__(self, bus):
        super().__init__(daemon=True, name="HJ3-Engine")
        self.bus = bus
        self._stop = threading.Event()
        self._control = threading.Event()   # armed state
        self._control_dirty = threading.Event()
        self.capture = None
        self.landmarker = None
        self._left_down = False
        self._cursor_hidden = False
        self._scroll_since = 0.0
        self._last_dt = 1 / 30
        self._prev_frame_t = 0.0
        self._burst_acc = 0
        self._cam_request = None
        self._preview_t = 0.0
        self._cam_index = int(settings.get("camera_index"))
        self._pv_logged = False
        self._pv_fail_logged = False
        self._estop_latch = False
        self._cfg_seen = None
        self._smoothing_seen = None
        self._hold_seen = None
        self._hands_seen = int(settings.get("max_hands") or 1)
        self._target_fps = 60 if int(settings.get("capture_fps") or 0) >= 60 else ENGINE_FPS_FALLBACK
        self._last_wall = time.time()
        self._trail_last = (0.0, 0.0)
        self._trail_t = 0.0
        self._trail_on = False          # set by _process_hand; the emitter feeds the trail
        self._driver_dialog = False     # UI asked for the camera driver property page
        self._slow_cam_streak = 0
        self._frozen_streak = 0
        self._edge_last = None          # last stable aim point (x, y) before an edge hold
        self._cam_mode = None           # (w, h) the ladder actually landed on
        self._rate_check_t = 0.0        # delivered-fps watchdog state
        self._rate_check_frames = 0
        self._rate_low_streak = 0
        self._rate_reopen_t = 0.0
        self._pred_seen = None
        self._model_seen = str(settings.get("model_file") or "")   # live model switching
        self._backend_seen = str(settings.get("backend") or "auto")  # live backend switching
        self._backend_name = "mediapipe"                             # what _load_model picked
        self._mp_image_cls = None       # set when the mediapipe backend loads (lazy import)
        self._last_frame_dark = False   # last read frame was (near) black
        self._cam_names = None          # index -> device name (lazy, per run)
        self._uniq_check_t = 0.0        # unique-frame watchdog state
        self._uniq_reopen_t = 0.0
        self._uniq_bad_streak = 0
        self._sig_ring = deque(maxlen=180)  # (t, 16x16 signature) of recent camera reads
        self._last_proc_sig = None      # signature of the last PROCESSED frame (dup gate)
        self._read_count = 0            # raw reads (rate watchdog); bus.frames counts processed
        self._dedupe = False            # True when the capture is a real camera we opened
        self._uniq_reopened_cam = None  # one-chance repeat reopen per camera (see unique watchdog)
        self._reader = None             # _CamReader while a capture is open
        self._reader_seq = 0            # sequence of the newest consumed frame
        self._last_frame_wall = time.time()  # wall time of the newest frame (read-stall watchdog)
        self._read_stalls = 0           # consecutive stall reopens (reset after a healthy minute)
        self._read_stall_t = 0.0
        self.sonar = None               # Sonar instance while enabled (experimental)
        self._sonar_fail = None         # key that failed to start — no retry spam
        self._sonar_last_error = None
        # high-rate motion engine: this thread ingests camera-rate samples, the
        # CursorMotion emitter thread produces the 120-200 Hz absolute-move stream
        self.motion = CursorMotion(
            prediction_ms=45, smoothness=settings.get("smoothing"), max_rate=144,
            speed_scale=max(1, bus.virtual_screen[2]) / 1920,
            hold_px=float(settings.get("hold_px") or 0.0))
        self.motion.set_output(self._emit_cursor)
        self._selector = G.PrimaryHandSelector()  # sticky primary-hand tracker
        self._active_hand = None        # index of the primary hand (preview highlight)
        self.start_t = 0.0
        # 3000: 3D pinch metric + debounced pose + telemetry
        self.pinch3d = PinchMeter3D()
        self.pose_tr = PoseTracker()
        self.edge = EdgeStabilizer()    # 2.1: frame-edge hold (jitter killer)
        # 2.2: landmark-level stabilization (adaptive 1€ filter + spike gate).
        # Separate filter state for image-space and world-space landmarks.
        self.lmsm = LandmarkStabilizer()
        self.lmsm_w = LandmarkStabilizer()
        self._lmsm_hand = None          # which hand index the filters follow
        self._stable_lms = None         # last stabilized frame (preview uses it)
        self.tel = Telemetry()
        self._prev_pose = "idle"
        self._infer_ms = 0.0

    # -- public controls (thread-safe) ---------------------------------------
    def arm(self, on):
        if on:
            self._control.set()
        else:
            self._control.clear()
        self._control_dirty.set()

    @property
    def armed(self):
        return self._control.is_set()

    def stop(self):
        self._stop.set()

    # -- lifecycle -----------------------------------------------------------
    def _open_camera(self, index, use_cache=True):
        """Open the camera at the highest mode that actually DELIVERS the rate.

        The decision is MEASURED (frames actually read), not requested, and it
        runs in a short-lived subprocess: opening a camera can crash the whole
        process at the driver level (seen in the wild when a virtual cam or a
        Camo/NVIDIA-Broadcast chain is mid-restart), so the probe must never
        take the app down with it. The processing downscale still happens in
        software in the engine loop.

        Fast path: the mode this camera landed on last time is tried directly
        (the full ladder boots a helper exe per rung, ~5-6 s of startup). The
        delivered-rate watchdog re-measures with the full ladder when the
        cached mode turns out to trickle."""
        fps = 60 if int(settings.get("capture_fps") or 0) >= 60 else 30
        if use_cache:
            cache = settings.get("cam_mode_cache") or {}
            cand = cache.get(str(int(index)))
            if isinstance(cand, (list, tuple)) and len(cand) == 2:
                try:
                    w, h = int(cand[0]), int(cand[1])
                except (TypeError, ValueError):
                    w = h = 0
                if w > 0 and h > 0:
                    cap = self._open_mode(index, w, h, fps)
                    if cap is not None:
                        self._cam_mode = (w, h)
                        log.info("camera %s: using saved mode %sx%s", index, w, h)
                        return cap
        order = [(CAPTURE_W, CAPTURE_H), (640, 480)]
        for w, h in order:
            measured = self._probe_capture_fps(index, w, h, fps, CAMERA_PROBE_S)
            if measured is None:
                continue
            last_rung = (w, h) == order[-1]
            if measured >= CAMERA_MIN_FPS or last_rung:
                if measured < CAMERA_MIN_FPS:
                    log.warning("camera %s: even 640x480 delivers only %.1f fps", index, measured)
                elif (w, h) != (CAPTURE_W, CAPTURE_H):
                    log.info("camera %s: 720p delivered %.1f fps -> fell back to 640x480", index, measured)
                cap = self._open_mode(index, w, h, fps)
                if cap is None:
                    continue
                self._cam_mode = (w, h)
                try:
                    cache = settings.get("cam_mode_cache") or {}
                    cache[str(int(index))] = [int(w), int(h)]
                    settings.set("cam_mode_cache", cache)
                except Exception:
                    pass
                return cap
            log.info("camera %s: 720p trickles at %.1f fps -> trying 640x480", index, measured)
        return None

    @staticmethod
    def _probe_capture_fps(index, w, h, fps, seconds):
        """Delivered fps for one (index, mode) — measured in a SUBPROCESS so a
        driver-level crash (access violation) cannot kill the app. Returns None
        when the mode can't deliver frames or the probe crashed."""
        import subprocess
        import sys as _sys
        if getattr(_sys, "frozen", False):
            # the frozen exe IS the app entry point: pass the flag directly
            cmd = [_sys.executable, "--camprobe", str(index), str(w), str(h), str(fps), str(seconds)]
        else:
            cmd = [_sys.executable, "-m", "handjob.main", "--camprobe",
                   str(index), str(w), str(h), str(fps), str(seconds)]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 12)
        except Exception as e:
            log.warning("camera probe %s failed to run: %s", index, e)
            return None
        for line in (p.stdout or "").splitlines():
            if line.startswith("CAMPROBE "):
                try:
                    return float(line.split()[1])
                except (IndexError, ValueError):
                    return None
        if p.returncode not in (0, 1):
            log.warning("camera probe %s crashed (rc=%s)", index, p.returncode)
        return None

    @staticmethod
    def _open_mode(index, w, h, fps):
        """Open one (backend, resolution) attempt; None when it can't deliver a frame."""
        for backend in (cv2.CAP_DSHOW, cv2.CAP_ANY):
            try:
                cap = cv2.VideoCapture(index, backend)
                if not cap.isOpened():
                    cap.release()
                    continue
                try:
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                except Exception:
                    pass
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                cap.set(cv2.CAP_PROP_FPS, fps)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                ok, _ = cap.read()
                if ok:
                    return cap
                cap.release()
            except Exception:
                continue
        return None

    @staticmethod
    def _frame_sig(frame):
        """Cheap fingerprint of a frame's content (16x16 gray, normalized)."""
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(g, (16, 16), interpolation=cv2.INTER_AREA).astype(np.int16)
        return small - int(small.mean())

    def _measure_unique_fps(self):
        """reads/s and UNIQUE frames/s over the last ~2 s of camera reads.

        Non-blocking: the loop feeds a cheap 16x16 signature per frame into
        `_sig_ring`; duplicates (virtual cams, low-light auto-exposure) show
        as pixel-identical consecutive signatures. A real sensor never repeats
        exactly (noise/auto-gain), so identical == genuinely repeated."""
        ring = self._sig_ring
        if len(ring) < 10:
            return None, None, None
        t0, t1 = ring[0][0], ring[-1][0]
        span = t1 - t0
        if span < 0.8:
            return None, None, None
        reads = len(ring) / span
        uniq = 0
        prev = None
        for _, sig in ring:
            if prev is not None and not _is_dup_sig(sig, prev):
                uniq += 1
            prev = sig
        return reads, uniq / span, None

    def _open_with_retry(self, cam, attempts=15, use_cache=True):
        cap = None
        tries = 0
        while cap is None and not self._stop.is_set() and tries < attempts:
            cap = self._open_camera(int(cam), use_cache=use_cache)
            tries += 1
            if cap is None:
                self.bus.error = f"camera {cam} busy — is another app using it?"
                time.sleep(1.2)
        return cap

    def _open_bounded(self, cam, deadline=None, use_cache=True):
        """`_open_with_retry` that can never block the engine for long: a wedged
        driver can hang VideoCapture()/the probe itself. On timeout the daemon
        helper is abandoned (if it later returns a capture, that handle is
        garbage-collected). Returns the capture or None."""
        deadline = CAMERA_OPEN_DEADLINE_S if deadline is None else deadline
        box = {}

        def work():
            box["cap"] = self._open_with_retry(cam, use_cache=use_cache)

        th = threading.Thread(target=work, daemon=True, name="HJ3-CamOpen")
        th.start()
        th.join(deadline)
        if th.is_alive():
            log.error("camera %s: open still running after %.0fs — driver looks stuck", cam, deadline)
            return None
        return box.get("cap")

    def _start_reader(self):
        """Wrap the current capture in a reader thread (idempotent)."""
        self._stop_reader()
        if self.capture is None:
            return
        self._reader = _CamReader(self.capture, max_hz=1.5 * float(self._target_fps))
        self._reader_seq = 0
        self._last_frame_wall = time.time()
        self._reader.start()

    def _stop_reader(self):
        """Detach the reader. A read stuck in a driver can't be interrupted, so
        the thread may be abandoned (daemon; it dies with the app). The app
        never blocks on it — that is the whole point of the reader design."""
        r = self._reader
        self._reader = None
        if r is None:
            return
        r.abandon()
        r.join(timeout=1.0)
        if r.is_alive():
            log.info("camera reader did not exit within 1 s — abandoning it (driver stuck)")

    def _stall_recover(self):
        """No frames for CAMERA_STALL_S: the read (or the whole driver) is stuck.
        Reopen bounded; give up with a clear error after repeated stalls.
        Returns False when the engine should give up."""
        self._read_stalls += 1
        self._read_stall_t = time.time()
        if _stall_decision(self._read_stalls, CAMERA_STALL_REOPENS) == "give_up":
            self._stop_reader()
            self.bus.error = ("camera keeps going silent — the driver looks stuck: close other camera "
                              "apps or pick another camera, then click Refresh app")
            log.error("camera %s: %d stalls in a row — giving up (driver stuck)",
                      self._cam_index, self._read_stalls)
            return False
        log.warning("camera %s: no frames for %.1fs — reopening (stall %d/%d)",
                    self._cam_index, time.time() - self._last_frame_wall,
                    self._read_stalls, CAMERA_STALL_REOPENS)
        self._stop_reader()
        self.capture = None
        cap = self._open_bounded(self._cam_index, use_cache=False)   # re-measure after a stall
        if cap is None:
            self.bus.error = (f"camera {self._cam_index} open is not responding — the driver looks "
                              "stuck; click Refresh app")
            return False
        self.capture = cap
        self._start_reader()
        self._last_proc_sig = None
        self._sig_ring.clear()
        self.bus.error = None
        log.info("camera %s reopened after stall", self._cam_index)
        return True

    def request_camera(self, idx, use_cache=True):
        """Ask the engine thread to switch cameras on its next frame.

        use_cache=False forces the full 720p->640x480 measurement ladder even
        when a cached mode exists (used when re-measuring after bad delivery)."""
        self._cam_request = (int(idx), bool(use_cache))

    def request_driver_settings(self):
        """Open the camera driver's own property page (DirectShow). This is where
        webcams hide "Low light compensation" / "Dynamic frame rate" — the usual
        reason a camera quietly drops to ~7-10 fps in a dim room."""
        self._driver_dialog = True

    def _cam_device_name(self):
        """Name of the active camera index (pygrabber, cached per app run; ""
        when enumeration is unavailable)."""
        try:
            if self._cam_names is None:
                self._cam_names = {int(c["index"]): str(c.get("name") or "")
                                   for c in list_cameras()}
            return self._cam_names.get(int(self._cam_index), "")
        except Exception:
            return ""

    def _load_model(self):
        """Load the configured inference backend.

        'auto'      — ONNX Runtime (DirectML GPU: ~0.6 ms/frame landmark stage
                      vs ~7.5 ms MediaPipe CPU) when available; MediaPipe CPU
                      is the always-present fallback.
        'onnx'      — ONNX Runtime (still falls back to MediaPipe if it cannot
                      start — a broken runtime must never brick the app).
        'mediapipe' — the original CPU pipeline.

        Custom .task models and 2-hand mode always use MediaPipe: the ONNX
        port covers the bundled lite model with one hand."""
        backend = str(settings.get("backend") or "auto")
        hands = int(settings.get("max_hands") or 1)
        wants_custom = bool(str(settings.get("model_file") or "").strip())
        if backend in ("auto", "onnx") and hands == 1 and not wants_custom:
            try:
                from .hand_onnx import OnnxHandLandmarker
                palm = os.path.join(assets_dir(), "hand_onnx", "palm_detection_full.onnx")
                land = os.path.join(assets_dir(), "hand_onnx", "hand_landmark_lite.onnx")
                self.landmarker = OnnxHandLandmarker(palm, land, num_hands=1)
                self._backend_name = "onnx (" + self.landmarker.backend() + ")"
                log.info("inference backend: %s", self._backend_name)
                return
            except Exception as e:
                log.warning("onnx backend unavailable (%s: %s) — using mediapipe",
                            type(e).__name__, e)
        path = _task_path(settings.get("model_file"))
        if not os.path.exists(path):
            # a stored custom model that vanished (deleted/renamed) -> bundled
            log.warning("model %s missing — falling back to the bundled default", path)
            settings.set("model_file", "")
            path = _task_path("")
        from mediapipe import Image as MpImage, ImageFormat
        from mediapipe.tasks.python import vision
        self._mp_image_cls, self._mp_image_fmt = MpImage, ImageFormat
        self.landmarker = vision.HandLandmarker.create_from_options(
            _landmarker_options(path, hands))
        self._backend_name = "mediapipe"
        log.info("inference backend: mediapipe (hands=%s%s)",
                 hands, ", custom model" if wants_custom else "")

    def run(self):
        try:
            self._run()
        except Exception as e:
            log.exception("engine crashed")
            self.bus.error = f"engine crashed: {e}"

    def _run(self):
        fake = os.environ.get("HJ3_FAKE_CAM")
        if fake:
            img = cv2.imread(fake)
            if img is not None:
                log.info("FAKE CAMERA mode: feeding %s", fake)
                self.capture = _FakeCapture(img)
            else:
                log.warning("HJ3_FAKE_CAM=%s could not be read — falling back to camera", fake)
        cam = int(settings.get("camera_index"))
        self._cam_index = cam
        cam_box = {}
        cam_th = None
        if not (self.capture and self.capture.isOpened()):  # reuse a pre-opened capture (probe flow)
            # open the camera WHILE the model loads — the mode probe boots a
            # helper exe per rung, and serialising it after the model cost
            # several seconds of startup
            def _boot_open():
                cam_box["cap"] = self._open_bounded(cam)
            cam_th = threading.Thread(target=_boot_open, daemon=True, name="HJ3-CamBoot")
            cam_th.start()
        try:
            self._load_model()
        except Exception as e:
            log.error("model load failed: %s", e)
            self.bus.error = f"model load failed: {e}"
            return
        log.info("model loaded: %s (num_hands=%s)", MODEL_NAME, self._hands_seen)
        if cam_th is not None:
            cam_th.join(timeout=CAMERA_OPEN_DEADLINE_S + 3)
            self.capture = cam_box.get("cap")
            self._dedupe = self.capture is not None        # dup gate: real cams only (probe/fake feeds differ every frame)
        if self.capture is None:
            log.error("camera %s not available", cam)
            self.bus.error = f"camera {cam} unavailable — close other camera apps and reopen"
            return
        self._start_reader()
        log.info("camera %s open, engine loop running", cam)
        self.start_t = time.time()
        first_frame_logged = False
        mapper = G.TravelMapper(sensitivity=settings.get("sensitivity"))
        clicks = ClickRefiner(threshold=settings.get("click_threshold"),
                              px_scale=max(1, self.bus.virtual_screen[2]) / 1920)
        scroll = G.ScrollAccumulator()
        self.motion.start()
        # the 144 Hz emitter + overlay threads need the GIL promptly; the default
        # 5 ms switch interval lets a busy thread hold it for several output ticks
        try:
            sys.setswitchinterval(0.001)
        except Exception:
            pass
        last_lost = 0.0
        ema_dt = 1 / 30
        last_beat = 0.0
        consecutive_errors = 0
        dark_since = 0.0
        while not self._stop.is_set():
            req = self._cam_request
            if req is not None:
                self._cam_request = None
                if isinstance(req, tuple):
                    req, req_use_cache = req
                else:
                    req_use_cache = True
                log.info("camera switch requested -> %s", req)
                self._stop_reader()
                self.capture = None
                self.capture = self._open_bounded(req, use_cache=req_use_cache)
                if self.capture is None:
                    log.error("camera switch to %s failed", req)
                    self.bus.error = f"camera {req} unavailable"
                else:
                    self._cam_index = req
                    self._dedupe = True
                    self.bus.error = None
                    self._frozen_streak = 0
                    self._read_stalls = 0
                    self._last_proc_sig = None
                    self._uniq_reopened_cam = None   # a manual switch re-arms the one-chance reopen
                    self._sig_ring.clear()
                    self._start_reader()
                    log.info("camera switched to %s", req)
            if self._driver_dialog:
                self._driver_dialog = False
                try:
                    self.capture.set(cv2.CAP_PROP_SETTINGS, 1)   # modal; returns when closed
                except Exception:
                    log.exception("camera driver settings dialog failed")
            # consume from the reader thread: a driver-blocked read() shows up
            # here as a get() timeout, never as a wedged engine loop
            if self._reader is None:
                time.sleep(0.05)                  # between cameras: don't spin
                item = None
            else:
                item = self._reader.get(self._reader_seq, 0.25)
            if item is None:
                if time.time() - self._last_frame_wall > CAMERA_STALL_S and not self._stall_recover():
                    return
                continue
            self._reader_seq, t_read, frame = item
            if frame is None:                     # the driver reports failed reads
                if time.time() - self._last_frame_wall > CAMERA_STALL_S and not self._stall_recover():
                    return
                time.sleep(0.05)
                continue
            self._last_frame_wall = t_read
            if self._read_stalls and time.time() - self._read_stall_t > 60.0:
                self._read_stalls = 0             # a healthy minute re-arms the reopen budget
            # TIMESTAMP = the moment the frame arrived. Everything downstream (landmark
            # filters, pose dwell, click timing, cursor velocity) works from this, not
            # from "after inference": inference time varies 10-30 ms frame to frame and
            # stamping after it injects that noise into every dt and velocity estimate.
            # cheap content signature for the unique-frame watchdog + dup gate (non-blocking)
            sig = None
            try:
                sig = self._frame_sig(frame)
                self._sig_ring.append((time.time(), sig))
            except Exception:
                pass
            self._read_count += 1
            # black-frame watchdog: time-based and READ-based, so it also fires
            # when a camera repeats ONE black frame (the old per-processed-frame
            # counter never advanced for duplicates — this exact case was blind).
            try:
                dark_now = float(np.mean(frame[::16, ::16])) < 2.0
            except Exception:
                dark_now = False
            self._last_frame_dark = dark_now
            if dark_now:
                if dark_since == 0.0:
                    dark_since = time.time()
                elif time.time() - dark_since > 3.0 and not self.bus.warning:
                    self.bus.warning = ("camera is delivering black frames — check the lens cover, "
                                        "Windows camera privacy settings, or the virtual camera's source")
                    log.warning("camera black-frame watchdog tripped")
            else:
                dark_since = 0.0
                if self.bus.warning and "black frames" in self.bus.warning:
                    self.bus.warning = None
            # delivered-rate watchdog: if the RAW read feed degrades below the usable
            # threshold after opening (USB power saving, another app), reopen
            # once so the 720p->640x480 ladder can re-measure. Never reopens
            # when already on the lowest rung. (Reads, not processed frames:
            # a repeating virtual cam answers plenty of reads.)
            wnow = time.time()
            if wnow - self._rate_check_t >= 3.0:
                dframes = self._read_count - self._rate_check_frames
                rate = dframes / max(1e-3, wnow - self._rate_check_t)
                self._rate_check_t = wnow
                self._rate_check_frames = self._read_count
                if 0.5 < rate < CAMERA_MIN_FPS and self._cam_mode != (640, 480):
                    self._rate_low_streak += 1
                    need = 1 if rate < 5.0 else 2       # clearly trickling: act on the first window
                    if self._rate_low_streak >= need and wnow - self._rate_reopen_t > 90.0:
                        self._rate_reopen_t = wnow
                        self._rate_low_streak = 0
                        log.warning("delivered rate %.1f fps — reopening camera to re-measure", rate)
                        self.request_camera(self._cam_index, use_cache=False)
                else:
                    self._rate_low_streak = 0
            # unique-frame watchdog: virtual cams and low-light auto-exposure
            # answer full reads but REPEAT frames (30 reads/s, ~10 new/s) —
            # the cursor then stutters at the unique rate. Detect + re-measure.
            if wnow - self._uniq_check_t >= 7.0:
                self._uniq_check_t = wnow
                rrate, urate, _ = self._measure_unique_fps()
                if rrate and urate is not None:
                    self.bus.cam_reads = round(rrate, 1)
                    self.bus.cam_unique = round(urate, 1)
                    # the camera itself is the bottleneck: tell the user, once, and
                    # name the actual device — the reason depends on WHAT it is, not
                    # on the read rate (a deep-idle virtual cam answers slowly, a
                    # busy one answers fast while repeating its standby screen).
                    if urate < 18.0:
                        self._slow_cam_streak += 1
                        if self._slow_cam_streak >= 2 and not self.bus.warning:
                            name = self._cam_device_name()
                            did = f"camera {self._cam_index}" + (f" ({name})" if name else "")
                            if self._last_frame_dark:
                                self.bus.warning = (f"{did} is delivering black frames — check the lens "
                                                    "cover or Windows camera privacy settings; for a virtual "
                                                    "camera, check its source app (it may be paused or "
                                                    "disconnected)")
                            elif _is_virtual_cam_name(name) or rrate > 40.0:
                                self.bus.warning = (f"{did} isn't delivering video "
                                                    f"(~{urate:.0f} new frames/s of {rrate:.0f} reads/s — reads "
                                                    "only mean the driver answers, not that the picture "
                                                    "changes). Its source app is paused, asleep, or the phone "
                                                    "is disconnected: unpause / reconnect it (Camo, NVIDIA "
                                                    "Broadcast, OBS). If it keeps happening with Camo, turn "
                                                    "OFF its auto-pause option, or pick another camera")
                            else:
                                self.bus.warning = (f"{did} delivers only ~{urate:.0f} new frames/s (tracking can't "
                                                    "be smoother than that). Usually dim light: add light, or open "
                                                    "Camera driver settings and turn off low-light compensation / "
                                                    "dynamic frame rate")
                    else:
                        self._slow_cam_streak = 0
                        if self.bus.warning and "new frames/s" in self.bus.warning:
                            self.bus.warning = None
                    if urate < 0.45 * rrate:
                        self._uniq_bad_streak += 1
                        log.info("camera unique-frame rate %.1f of %.1f reads/s", urate, rrate)
                        # one chance per camera: reopen once in case the driver got into a
                        # stale-buffer state; a chronic repeater (virtual cam) can't be
                        # fixed by reopening — the pipeline now handles repeats instead.
                        if (self._frozen_streak < 2 and self._uniq_bad_streak >= 2
                                and wnow - self._uniq_reopen_t > 120.0
                                and self._uniq_reopened_cam != self._cam_index):
                            self._uniq_reopen_t = wnow
                            self._uniq_bad_streak = 0
                            self._uniq_reopened_cam = self._cam_index
                            log.warning("camera repeats frames (%.1f unique of %.1f reads/s) — reopening once",
                                        urate, rrate)
                            self.request_camera(self._cam_index)
                    else:
                        self._uniq_bad_streak = 0
                    # frozen source (virtual cam with a dead upstream): the cursor would
                    # creep from landmark noise on a still image — halt it and say so
                    self._frozen_streak, faction = _frozen_cam_state(urate, self._frozen_streak)
                    if faction == "error" and not (self.bus.error or "").startswith("camera frozen"):
                        self.bus.error = FROZEN_ERR
                        log.error("camera frozen: %.1f unique of %.1f reads/s — halting cursor", urate, rrate)
                        self.motion.halt()
                    elif faction == "clear" and (self.bus.error or "").startswith("camera frozen"):
                        self.bus.error = None
                        log.info("camera live again (%.1f new frames/s)", urate)
            if not first_frame_logged:
                first_frame_logged = True
                log.info("first frame captured %sx%s (target %s Hz, num_hands=%s)",
                         frame.shape[1], frame.shape[0], self._target_fps, self._hands_seen)
            cfg = settings.get()
            # dt-scaled prediction: the emitter needs a camera interval of lead
            # to interpolate across; at ~10 fps feeds the slider value alone
            # leaves the cursor jumping between samples.
            pred = _effective_prediction(cfg["prediction_ms"], self._last_dt)
            if (cfg["smoothing"] != self._smoothing_seen or pred != self._pred_seen
                    or float(cfg.get("hold_px") or 0.0) != self._hold_seen):
                self._smoothing_seen = cfg["smoothing"]
                self._pred_seen = pred
                self._hold_seen = float(cfg.get("hold_px") or 0.0)
                self.motion.configure(smoothness=cfg["smoothing"], prediction_ms=pred,
                                      hold_px=self._hold_seen)
            mapper.sensitivity = cfg["sensitivity"]
            clicks.pinch.threshold = cfg["click_threshold"]
            clicks.drag_px = cfg["drag_px"]
            scroll.deadzone = cfg["scroll_deadzone"]

            # capture-rate change -> reopen the camera at the new rate
            fps = 60 if float(cfg.get("capture_fps") or 0) >= 60 else 30
            if fps != self._target_fps:
                self._target_fps = fps
                self.request_camera(self._cam_index)
            # hand-count change -> rebuild the landmarker (each hand costs ~7 ms/frame)
            hands = int(cfg.get("max_hands") or 1)
            if hands != self._hands_seen:
                self._hands_seen = hands
                try:
                    self.landmarker.close()
                except Exception:
                    pass
                try:
                    self._load_model()
                    log.info("landmarker reloaded (num_hands=%s)", hands)
                except Exception:
                    log.exception("landmarker reload failed")
            # model change -> rebuild the landmarker on the new file (live switch;
            # a bad file falls back to the bundled default instead of dying)
            model_now = str(cfg.get("model_file") or "")
            if model_now != self._model_seen:
                self._model_seen = model_now
                try:
                    self.landmarker.close()
                except Exception:
                    pass
                try:
                    self._load_model()
                    log.info("model switched -> %s", _task_base(model_now) or MODEL_NAME)
                except Exception:
                    log.exception("model switch failed — reverting to the bundled default")
                    settings.set("model_file", "")
                    self._model_seen = ""
                    try:
                        self._load_model()
                    except Exception:
                        log.exception("bundled model reload failed")
            # inference-backend change -> rebuild the landmarker on the other runtime
            backend_now = str(cfg.get("backend") or "auto")
            if backend_now != self._backend_seen:
                self._backend_seen = backend_now
                try:
                    self.landmarker.close()
                except Exception:
                    pass
                try:
                    self._load_model()
                    log.info("inference backend switched -> %s", self._backend_name)
                except Exception:
                    log.exception("backend switch failed")

            # ------- duplicate-frame gate (virtual cams) ------------------------
            # Camo / NVIDIA Broadcast / OBS answer every read by repeating the last
            # frame until their source produces a new one (the user's log: "8.5
            # unique of 54.7 reads/s"). Feeding those repeats downstream puts the
            # real 67 ms of hand motion into an 18 ms dt -> velocity ~3.7x too high
            # -> the 1-euro cutoff boost passes each new frame almost unfiltered ->
            # the cursor lurches on every update and stalls in between. That IS the
            # "jitters / not smooth / delayed" feel. Drop repeats here: inference,
            # landmark filter, click timing and motion all advance only on genuinely
            # new frames, so every dt is honest; the emitter interpolates across
            # the (now longer, correctly measured) gaps. Also skips ~80% of the
            # CPU work on a repeating camera. Real cameras never repeat exactly
            # (sensor noise), so this only fires for duplicates.
            if self._dedupe and sig is not None and _is_dup_sig(sig, self._last_proc_sig):
                # pace against t_read (a WALL clock) — mixing perf_counter with
                # t_read here once slept for ~56 years: budget - (perf_counter -
                # time.time()) is a ~1.7e9-positive number, so the engine froze
                # on the first repeated frame (any static scene on a vcam).
                wait = budget_dup = 1.0 / self._target_fps
                spent = time.time() - t_read
                wait -= spent
                if wait > 0:                  # vcams answer instantly: don't spin
                    time.sleep(min(wait, budget_dup))
                continue
            self._last_proc_sig = sig

            t0 = time.perf_counter()
            try:
                # software downscale (no driver crops): the camera delivers its
                # native mode, we shrink the FULL frame to the processing size
                proc_h = int(cfg.get("capture_height") or 480)
                h, w = frame.shape[:2]
                if 0 < proc_h < h:
                    frame = cv2.resize(frame, (max(2, int(round(w * proc_h / float(h)))), proc_h),
                                       interpolation=cv2.INTER_AREA)
                frame = cv2.flip(frame, 1)  # selfie view: hand right = screen right
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                t_inf = time.perf_counter()
                if self._mp_image_cls is not None:
                    res = self.landmarker.detect_for_video(
                        self._mp_image_cls(image_format=self._mp_image_fmt.SRGB, data=rgb),
                        int(t0 * 1000))
                else:
                    res = self.landmarker.detect_for_video(rgb, int(t0 * 1000))
                self._infer_ms = (time.perf_counter() - t_inf) * 1000.0
            except Exception:
                consecutive_errors += 1
                log.exception("inference failed (%d consecutive)", consecutive_errors)
                if consecutive_errors == 15:
                    log.warning("recreating the landmarker after repeated inference errors")
                    try:
                        self.landmarker.close()
                    except Exception:
                        pass
                    try:
                        self._load_model()
                        consecutive_errors = 0
                        time.sleep(0.2)
                        continue
                    except Exception:
                        log.exception("landmarker recreate failed")
                if consecutive_errors > 45:
                    self.bus.error = "inference keeps failing — click Refresh app"
                    return
                time.sleep(0.05)
                continue
            consecutive_errors = 0

            now = t_read
            self._last_dt = (max(1e-3, min(0.2, now - self._prev_frame_t))
                             if self._prev_frame_t else 1 / 30)
            self._prev_frame_t = now
            if self._estop_pressed():
                if self.armed:
                    log.info("PANIC STOP (Ctrl+Alt+H) — disarming")
                    self._control.clear()
                    self._control_dirty.set()
            if self._control_dirty.is_set():
                self._control_dirty.clear()
                if not self.armed:
                    self._release_all(clicks)

            try:
                if res.hand_landmarks:
                    # primary-hand rule: the first hand that appears keeps the
                    # cursor; a hand popping into frame later never steals it.
                    anchors = [G.palm_center([(lm.x, lm.y, lm.z) for lm in h])
                               for h in res.hand_landmarks]
                    idx = self._selector.select(anchors, now)
                    self._active_hand = idx
                    if idx is not None:
                        if self._lmsm_hand != idx:      # primary hand switched
                            self.lmsm.reset()
                            self.lmsm_w.reset()
                            self._lmsm_hand = idx
                        hand_lms = res.hand_landmarks[idx]
                        lms = [(lm.x, lm.y, lm.z) for lm in hand_lms]
                        world = None
                        try:
                            if res.hand_world_landmarks:
                                world = [(w.x, w.y, w.z) for w in res.hand_world_landmarks[idx]]
                        except (IndexError, TypeError):
                            world = None
                        # 2.2 landmark stabilization: adaptive smoothing + spike
                        # gate — pose, pinch and the cursor all read the cleaned
                        # stream, so a single noisy frame can't flip anything.
                        lms = self.lmsm.process(lms, now)
                        if world is not None:
                            world = self.lmsm_w.process(world, now)
                        self._stable_lms = lms
                        self._process_hand(lms, mapper, clicks, scroll, cfg, now, frame, world=world)
                        last_lost = now
                    elif now - self._selector.last_seen > self._selector.grace:
                        # the primary hand has been gone past its grace window —
                        # the next hand present will be adopted instead
                        self._on_hand_lost(clicks)
                else:
                    self._active_hand = None
                    if self._selector.last_seen is not None and now - self._selector.last_seen > self._selector.grace:
                        self._on_hand_lost(clicks)
                    if self._left_down:
                        # brief loss during drag: keep button held (avoid dropping drags)
                        if now - last_lost > 0.9:
                            self._mouse_up("left")
                self._draw_preview(frame, res, cfg, now)
                self._publish_stats(t0, res)
            except Exception:
                log.exception("frame processing failed")
            try:
                self._sync_sonar(cfg)
            except Exception:
                log.exception("sonar sync failed")
            # pace to the target rate: an uncapped loop starves the UI thread of GIL
            spent = time.perf_counter() - t0
            budget = 1.0 / self._target_fps
            if spent < budget:
                time.sleep(budget - spent)
            if now - last_beat > 5:
                last_beat = now
                log.info("beat frames=%s fps=%.1f lat=%.1fms armed=%s found=%s err=%s",
                          self.bus.frames, self.bus.fps, self.bus.latency_ms,
                          self.armed, self.bus.found, self.bus.error)
        self.motion.stop()
        # restore the OS cursor from THIS thread before exiting (ShowCursor is thread-affine)
        try:
            wi.show_cursor(True)
            self._cursor_hidden = False
        except Exception:
            pass

    # -- sonar supervision (experimental; never drives the cursor) -----------
    def _sync_sonar(self, cfg):
        """Start/stop/restart the sonar sensing to match the settings."""
        want = bool(cfg.get("sonar_enabled"))
        key = (int(cfg.get("sonar_in_device", -1)), int(cfg.get("sonar_out_device", -1)),
               int(cfg.get("sonar_tone", 19000)))
        if not want:
            if self.sonar is not None:
                self.sonar.stop()
                self.sonar = None
                log.info("sonar stopped")
            self._sonar_fail = None
            return
        if self.sonar is not None and self.sonar.key != key:
            self.sonar.stop()
            self.sonar = None
        if self.sonar is None and self._sonar_fail != key:
            try:
                from .sonar import Sonar
                s = Sonar(in_dev=key[0], out_dev=key[1], tone=key[2])
                s.start()
                self.sonar = s
                self._sonar_last_error = None
                log.info("sonar started: %s", s.status())
            except Exception as e:
                self._sonar_fail = key
                self._sonar_last_error = f"{type(e).__name__}: {e}"
                log.warning("sonar unavailable: %s", self._sonar_last_error)

    # -- per-frame processing ------------------------------------------------
    def _process_hand(self, lms, mapper, clicks, scroll, cfg, now, frame, world=None):
        bus = self.bus
        # 3000: pinch measured in 3D world coordinates (thumb in FRONT of a finger
        # is no longer a click); pose stays 2D but is debounced by PoseTracker.
        l_ratio, r_ratio = self.pinch3d.update(world, lms, now)
        thr = clicks.pinch.threshold
        raw_pose = G.classify_pose(lms, pinching=(l_ratio < 1.5 * thr or r_ratio < 1.5 * thr))
        pose = self.pose_tr.update(raw_pose, now, holding=clicks.left_down or clicks.right_held)

        armed = self.armed
        # cursor anchor = the index fingertip (the point the user aims with)
        tx, ty = G.track_point(lms)
        # 2.1 edge hold: landmark noise explodes as the hand starts leaving the
        # frame; inside the margin band the LAST stable aim point keeps driving
        # the cursor, so edge jitter never reaches the screen. The rest of the
        # flow is unchanged — the hold only substitutes the position downstream.
        self.edge.margin = float(cfg.get("edge_margin", 0.04) or 0.0)
        hold = self.edge.update(tx, ty)
        if hold:
            if self._edge_last is not None:
                tx, ty = self._edge_last
        else:
            self._edge_last = (tx, ty)
        vw, vh = bus.virtual_screen[2], bus.virtual_screen[3]
        reanchored = False
        if pose == "point" and self._prev_pose != "point":
            # pick-up mapping: entering point makes the hand's CURRENT position map
            # onto the cursor's CURRENT position — no jump on (re)engage
            if cfg.get("reanchor", True):
                cur = self.motion.position or os_cursor_pos() or (vw / 2.0, vh / 2.0)
                reanchor(mapper, tx, ty, cur, vw, vh)
                reanchored = True
            else:
                mapper.update_center(tx, ty, self._last_dt)
        self._prev_pose = pose
        sx, sy = mapper.to_screen(tx, ty, vw, vh)
        # the click refiner sees the RAW mapped position and owns the freeze /
        # drag / anchor targeting; the motion engine owns smoothing + prediction
        if reanchored:
            # the mapped position teleported on purpose: drop pre-jump history
            # so a pinch already in progress can't anchor at stale coordinates
            clicks.reseed(now, sx, sy)
        else:
            clicks.observe(now, sx, sy)
        try:
            self.tel.frame(now, self._infer_ms, raw_pose, pose, l_ratio, r_ratio, hold)
        except Exception:
            pass
        # peace-sign scroll tracks the index+middle midpoint (hand up/down)
        scroll_y = (lms[G.INDEX_TIP][1] + lms[G.MIDDLE_TIP][1]) / 2.0

        if pose == "point":
            # one thumb serves both pins: only the clearly-closer finger counts
            l_feed, r_feed = G.disambiguate_pinches(l_ratio, r_ratio, clicks.pinch.threshold)
            events = clicks.update_left(l_feed, now) + clicks.update_right(r_feed, now)
        else:
            # scroll/idle behave as "not pinching": frees any held button and
            # re-arms the pinch state machines
            events = clicks.release_all(now)
        notches = scroll.update(scroll_y, active=(pose == "scroll"),
                                speed=cfg["scroll_speed"] * 3,
                                invert=cfg["invert_scroll"])

        if armed:
            for ev in events:
                if ev == "left_down":
                    ax, ay = clicks.anchor or (sx, sy)
                    self.motion.snap(ax, ay)     # land exactly on the anchor, then press
                    self._mouse_down("left")
                    bus.press = 0.75
                    bus.pulse = (ax, ay, now)
                    self.tel.event(now, "left_down")
                elif ev == "left_up":
                    self._mouse_up("left")
                    bus.press = 0.0
                    self.tel.event(now, "left_up")
                elif ev == "right_click":
                    ax, ay = clicks.anchor or (sx, sy)
                    self.motion.snap(ax, ay)
                    self._mouse_click("right")
                    bus.pulse = (ax, ay, now)
                    self.tel.event(now, "right_click")

            # cursor motion only while pointing — scroll and idle freeze it
            if pose == "point":
                cx, cy = clicks.cursor_target(now)   # anchor / drag ramp / live pos
                self.motion.ingest(now, cx, cy)      # motion owns all output from here
                if self._left_down and clicks.state == "drag" and cfg.get("sparkles", True):
                    self._sparkle_burst(cx, cy, now)
            else:
                self.motion.halt()                   # clutch: freeze in place, no run-on
            if notches:
                wi.wheel(int(max(-10, min(10, notches))))
        else:
            self.motion.halt()

        with bus.lock:
            bus.found = True
            bus.dim = False
            bus.armed = armed
            bus.style = cfg["cursor_style"]
        if pose == "point":
            # overlay glue: show the ACTUAL emitted position (the emitter thread
            # runs at ~144 Hz; this is what the OS cursor displays)
            pos = self.motion.position
            if pos is not None:
                with bus.lock:
                    bus.position = pos
        # trail points come from _emit_cursor (emitter rate, smoothed) — feeding
        # them from here made the trail a 30 Hz staircase behind a smooth ring
        self._trail_on = bool(cfg["trail"] and armed and pose == "point")

        # hide the OS arrow while the custom orb is live; restore otherwise
        want_hidden = armed and cfg["cursor_style"] != "system"
        if want_hidden != self._cursor_hidden:
            wi.show_cursor(not want_hidden)
            self._cursor_hidden = want_hidden

    def _sparkle_burst(self, x, y, now):
        self._burst_acc += 1
        if self._burst_acc % 2:
            self.bus.spawn_sparkles(x, y, now, n=2)

    def _estop_pressed(self):
        """Ctrl+Alt+H panic stop, polled (no RegisterHotKey plumbing needed)."""
        u = wi.user32
        try:
            down = bool((u.GetAsyncKeyState(0x11) & 0x8000)
                        and (u.GetAsyncKeyState(0x12) & 0x8000)
                        and (u.GetAsyncKeyState(0x48) & 0x8000))
        except Exception:
            return False
        if down and not self._estop_latch:
            self._estop_latch = True
            return True
        if not down:
            self._estop_latch = False
        return False

    def _on_hand_lost(self, clicks):
        with self.bus.lock:
            self.bus.found = False
            self.bus.dim = True
            self.bus.press = 0.0
        if self._cursor_hidden:
            wi.show_cursor(True)
            self._cursor_hidden = False
        clicks.reset()
        self.pinch3d.reset()
        self.pose_tr.reset()
        self.edge.reset()
        self.lmsm.reset()
        self.lmsm_w.reset()
        self._lmsm_hand = None
        self._stable_lms = None
        self._edge_last = None
        self._trail_on = False
        self.motion.halt()
        if self._left_down:
            self._mouse_up("left")

    def _draw_preview(self, frame, res, cfg, now=None):
        """Preview modes: wireframe (hand skeleton only, default) | camera | off.

        Draws on the PROCESSED frame (post downscale) so the preview shows
        exactly what the tracker sees; encoded at ~12 fps max — the UI polls
        the newest JPEG, so a slower preview costs nothing visually and saves
        real CPU.
        """
        mode = cfg.get("preview_mode", "wireframe")
        if mode == "off":
            return
        now = now or time.time()
        if now - self._preview_t < PREVIEW_MIN_INTERVAL:
            return
        self._preview_t = now
        h, w = frame.shape[:2]
        canvas = np.zeros_like(frame) if mode == "wireframe" else frame
        lw = max(1, w // 320)
        dot = max(2, w // 200)
        if res.hand_landmarks:
            for hi, hand in enumerate(res.hand_landmarks):
                primary = (hi == self._active_hand)
                pts = [(int(lm.x * w), int(lm.y * h)) for lm in hand]
                if primary and self._stable_lms is not None and len(self._stable_lms) == len(hand):
                    pts = [(int(p[0] * w), int(p[1] * h)) for p in self._stable_lms]
                color = SKY_BGR if primary else (110, 116, 128)
                for a, b in HAND_CONNECTIONS:
                    cv2.line(canvas, pts[a], pts[b], color, lw + 1 if primary else 1, cv2.LINE_AA)
                for p in pts:
                    cv2.circle(canvas, p, dot, WHITE_BGR if primary else color, -1, cv2.LINE_AA)
                if primary:
                    for a, b in ((4, 12), (4, 16)):  # thumb->middle / thumb->ring pinch links
                        cv2.line(canvas, pts[a], pts[b], SKY_BGR, 1, cv2.LINE_AA)
        ok, jpg = cv2.imencode(".jpg", canvas, PREVIEW_JPEG_QUALITY["jpg"])
        if ok:
            blob = jpg.tobytes()
            self.bus.set_preview(blob)
            if not self._pv_logged:
                self._pv_logged = True
                log.info("preview first frame (%s mode): %d bytes", mode, len(blob))
        elif not self._pv_fail_logged:
            self._pv_fail_logged = True
            log.warning("preview encode failed")

    def _publish_stats(self, t0, res):
        dt = time.perf_counter() - t0
        bus = self.bus
        with bus.lock:
            bus.frames += 1
            bus.latency_ms = bus.latency_ms * 0.9 + dt * 1000 * 0.1
            if bus.frames % 15 == 0:
                now = time.time()
                span = now - self.start_t
                if span > 0:
                    bus.fps = 15 / span
                self.start_t = now

    # -- mouse helpers -------------------------------------------------------
    def _mouse_down(self, which):
        wi.button(which, True)
        if which == "left":
            self._left_down = True

    def _mouse_up(self, which):
        wi.button(which, False)
        if which == "left":
            self._left_down = False

    def _mouse_click(self, which):
        wi.button(which, True)
        wi.button(which, False)

    def _emit_cursor(self, x, y):
        """CursorMotion sink (runs on the emitter thread): OS move + bus mirror.

        Called only on whole-pixel changes, so this doubles as the deadzone."""
        wi.move_absolute(x, y)
        bus = self.bus
        with bus.lock:
            bus.position = (x, y)
        if self._trail_on:
            tn = time.time()
            if tn - self._trail_t >= 0.010 and math.dist((x, y), self._trail_last) >= 3.0:
                self._trail_t = tn
                self._trail_last = (x, y)
                bus.update_trail(x, y, tn)      # also wakes the overlay
                return
        bus.visual_event.set()

    def _release_all(self, clicks):
        if self._left_down:
            self._mouse_up("left")
        clicks.reset()
        self.motion.halt()
        # re-arm the motion engine cleanly: drop all history and glide from the
        # current position (a fresh arm must not carry stale velocity)
        pos = self.motion.position
        if pos is not None:
            self.motion.snap(pos[0], pos[1])
        wi.show_cursor(True)
        self._cursor_hidden = False

    def cleanup(self):
        try:
            if self._left_down:
                self._mouse_up("left")
            wi.show_cursor(True)
        except Exception:
            pass
        try:
            if self.sonar is not None:
                self.sonar.stop()
                self.sonar = None
        except Exception:
            pass
        try:
            had_reader = self._reader is not None
            self._stop_reader()          # never block app exit on a stuck driver
            if self.capture is not None and not had_reader:
                cap, self.capture = self.capture, None
                threading.Thread(target=self._safe_release, args=(cap,), daemon=True).start()
            if self.landmarker:
                self.landmarker.close()
        except Exception:
            pass

    @staticmethod
    def _safe_release(cap) -> None:
        try:
            cap.release()
        except Exception:
            pass


def list_cameras(max_index=5):
    """Camera index -> name list, WITHOUT opening any device.

    Opening cameras to probe them can crash the whole process at the driver
    level (access violation — seen with virtual cams mid-restart), so
    enumeration reads the DirectShow device list instead (pygrabber).
    Returns [{"index": i, "name": name}]; the order matches the DSHOW indices
    OpenCV uses. Falls back to bare indices if the enumerator is unavailable.
    """
    try:
        from pygrabber.dshow_graph import FilterGraph
        names = FilterGraph().get_input_devices()
        if names:
            return [{"index": i, "name": n} for i, n in enumerate(names)]
    except Exception:
        log.exception("camera name enumeration failed")
    return [{"index": i, "name": f"Camera {i}"} for i in range(max_index + 1)]
