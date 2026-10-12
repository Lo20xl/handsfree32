"""HandJob3000 entry point: API for the UI + pywebview window."""
import argparse
import ctypes
import logging
import math
import os
import sys
import threading
import time

from . import APP_NAME, __version__
from . import settings
from .paths import LOG_PATH

log = logging.getLogger("handjob")


def _setup_logging(verbose=False):
    try:
        import faulthandler
        _crash = open(os.path.join(os.path.dirname(LOG_PATH), "crash.log"), "a", encoding="utf-8")
        _crash.write("\n=== RUN START %s pid=%s ===\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid()))
        _crash.flush()
        faulthandler.enable(file=_crash, all_threads=True)
    except Exception:
        pass
    try:
        logging.basicConfig(
            filename=LOG_PATH,
            level=logging.DEBUG if verbose else logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    except Exception:
        logging.basicConfig(level=logging.INFO)  # console fallback
    logging.getLogger("PIL").setLevel(logging.WARNING)


def _dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE_V2
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class Api:
    """Bridge exposed to JS as pywebview.api.<method>."""

    def __init__(self):
        from .engine import CursorBus, Engine, list_cameras
        self._list_cameras = list_cameras
        self.bus = CursorBus()
        self.engine = Engine(self.bus)
        self._engine_started = False
        self.overlay = None
        self._lock = threading.Lock()

    # -- lifecycle -----------------------------------------------------------
    def start(self):
        from .overlay import Overlay
        settings.load()
        self.overlay = Overlay(self.bus)
        self.overlay.start()
        self.engine.start()
        self._engine_started = True
        if settings.get("start_enabled"):
            time.sleep(0.2)
            self.set_control(True)

    def shutdown(self):
        try:
            self.engine.arm(False)
            self.engine.stop()
            self.engine.cleanup()
        except Exception:
            log.exception("engine shutdown")
        if self.overlay:
            self.overlay.stop()
        try:
            settings.save()
        except Exception:
            pass

    # -- settings ------------------------------------------------------------
    def get_settings(self):
        return settings.get()

    def set_setting(self, key, value):
        try:
            snap = settings.set(str(key), value)
            log.info("setting %s=%r", key, value)
            return {"ok": True, "settings": snap}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def reset_settings(self):
        return {"ok": True, "settings": settings.reset()}

    # -- engine --------------------------------------------------------------
    def set_control(self, on):
        on = bool(on)
        self.engine.arm(on)
        log.info("control %s", "ARMED" if on else "disarmed")
        return self.get_state()

    def get_state(self):
        bus = self.bus
        # One local reference for the whole call: self.engine is only ever
        # reassigned inside refresh_app, and reading it field-by-field while a
        # refresh swaps it mid-dict is a torn-state race.
        eng = self.engine
        # cam_name MUST be resolved outside bus.lock: the first call after a
        # refresh_app runs a full DirectShow/COM device enumeration (tens of ms),
        # which used to block the engine's bus.position write and the overlay's
        # snapshot() for the entire enumeration.
        cam_name = eng._cam_device_name()
        with bus.lock:
            return {
                "armed": eng.armed,
                "engine_started": self._engine_started,
                "hand_found": bus.found,
                "fps": round(bus.fps, 1),
                "latency_ms": round(bus.latency_ms, 1),
                "error": bus.error,
                "warning": bus.warning,
                "cursor_style": bus.style,
                "settings": settings.get(),
                "version": __version__,
                "log_path": LOG_PATH,
                "infer_ms": round(eng._infer_ms, 1),
                "pose": eng._prev_pose,
                "pinch_l": self._pinch()[0],
                "pinch_r": self._pinch()[1],
                "sonar": self._sonar_state(),
                "cam_reads": bus.cam_reads,
                "cam_unique": bus.cam_unique,
                "backend": getattr(eng, "_backend_name", "mediapipe"),
                "cam_name": cam_name,
            }

    def _sonar_state(self):
        """Sonar diagnostics for the UI (experimental sensing channel)."""
        from .sonar import CARRIER_MIN_DB
        eng = self.engine
        so = getattr(eng, "sonar", None)
        err = getattr(eng, "_sonar_last_error", None)
        try:
            from .sonar import sd as _sd
            available = _sd is not None
        except Exception:
            available = False
        diag = dict(getattr(so, "diag", {}) or {}) if so is not None else {}
        # A tone the mic cannot hear is a hardware limit, not a fault — say so
        # instead of showing "motion 0.00" forever, which reads as broken.
        note = None
        if so is not None and diag.get("blocks", 0) > 12 and not diag.get("carrier_ok", True):
            note = (f"{diag.get('tone', 0):.0f} Hz tone not audible to this mic "
                    f"(+{diag.get('carrier_db', 0):.0f} dB over floor, needs "
                    f"+{CARRIER_MIN_DB:.0f}) — try another tone or audio device")
        out = {"available": available,
               "enabled": bool(settings.get("sonar_enabled")),
               "diag": diag,
               "carrier_ok": diag.get("carrier_ok"),
               "note": note,
               "error": err if (err and so is None) else None,
               "in_device": int(settings.get("sonar_in_device")),
               "out_device": int(settings.get("sonar_out_device"))}
        return out

    def _pinch(self):
        """(l, r) from the newest telemetry frame — the live pinch meter readings."""
        try:
            f = self.engine.tel.f
            if f:
                return (round(f[-1][4], 3), round(f[-1][5], 3))
        except Exception:
            pass
        return (None, None)

    def get_telemetry(self):
        """Full diagnostics text: fps/interval, inference, pose flicker, pinch stats,
        emitter health. Paste-able (the calibration/troubleshooting payload)."""
        eng = self.engine
        try:
            summary = eng.tel.summary(eng.motion)
        except Exception as e:
            summary = f"telemetry unavailable: {e}"
        return {"ok": True, "summary": summary}

    # -- media ---------------------------------------------------------------
    def preview(self, last_seq=None):
        """Preview frame for the UI.

        Legacy call (no argument): the newest frame as a data URL, or None.
        With `last_seq`: long-poll — waits up to ~60 ms for a frame NEWER than
        that sequence number and returns {"seq": n, "img": dataURL | None}. The
        UI loop then runs at the preview's real rate (the old loop slept 110 ms
        between polls = a hard ~9 fps ceiling, which looked like tracking at 10 fps)."""
        if last_seq is not None:
            try:
                seq, img = self.bus.wait_preview(int(last_seq))
            except Exception:
                seq, img = int(last_seq), None
            return {"seq": seq, "img": img}
        blob = self.bus.get_preview()
        if blob is None:
            self._pv_miss = getattr(self, "_pv_miss", 0) + 1
            if self._pv_miss % 100 == 1:
                log.warning("preview polled but empty (frames=%s)", self.bus.frames)
        else:
            self._pv_hit = getattr(self, "_pv_hit", 0) + 1
            if self._pv_hit == 1:
                log.info("preview first served: %d chars", len(blob))
        return blob

    def cameras(self):
        """Camera index -> name list (no device opens — enumeration is crash-safe)."""
        out = self._list_cameras()
        seen = {c["index"] for c in out}
        cur = int(settings.get("camera_index"))
        if cur not in seen:                      # saved index no longer enumerates
            out.append({"index": cur, "name": f"Camera {cur} (not detected)"})
        return out

    def models(self):
        """Model choices for the picker: bundled default + imported .task files."""
        from .engine import list_models
        return {"models": list_models(), "current": str(settings.get("model_file") or "")}

    def set_model(self, file=""):
        settings.set("model_file", str(file or ""))
        log.info("setting model_file=%r", file)
        return self.get_state()

    def import_model(self):
        """File picker -> validate -> copy into models/ -> return the new list."""
        from .engine import import_model, list_models
        win = getattr(self, "_window", None)
        if win is None:
            return {"ok": False, "error": "window not ready"}
        try:
            import webview
            picked = win.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=False,
                file_types=("MediaPipe models (*.task)", "All files (*.*)"))
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if not picked:
            return {"ok": False, "cancelled": True}
        src = picked[0] if isinstance(picked, (list, tuple)) else picked
        try:
            stored = import_model(str(src))
        except Exception as e:
            log.warning("model import rejected: %s", e)
            return {"ok": False, "error": str(e)}
        return {"ok": True, "file": stored, "models": list_models()}

    def sonar_devices(self):
        """(inputs, outputs) as [index, name] pairs for the Sonar card selects.

        Devices are listed across host APIs (the built-in mic/speakers on many
        laptops only appear under WDM-KS); the API name is part of the label so
        picking a working endpoint is easy when several duplicates exist.
        """
        inputs, outputs = [], []
        try:
            from .sonar import sd
            if sd is None:
                return {"inputs": inputs, "outputs": outputs, "available": False}
            apis = {}
            try:
                apis = {i: str(a.get("name", f"api {i}")) for i, a in enumerate(sd.query_hostapis())}
            except Exception:
                pass
            default_in, default_out = -1, -1
            try:
                d = sd.default.device
                if isinstance(d, (list, tuple)) and len(d) == 2:
                    default_in, default_out = int(d[0] or -1), int(d[1] or -1)
            except Exception:
                pass
            for i, dev in enumerate(sd.query_devices()):
                try:
                    name = str(dev.get("name", f"device {i}"))
                    api = apis.get(int(dev.get("hostapi", -1)), "")
                    tag = f" [{api}]" if api else ""
                    if int(dev.get("max_input_channels", 0)) > 0:
                        star = " ★ default" if i == default_in else ""
                        inputs.append([i, f"{name}{tag}{star}"])
                    if int(dev.get("max_output_channels", 0)) > 0:
                        star = " ★ default" if i == default_out else ""
                        outputs.append([i, f"{name}{tag}{star}"])
                except Exception:
                    continue
            return {"inputs": inputs, "outputs": outputs, "available": True}
        except Exception as e:
            log.warning("sonar device probe failed: %s", e)
            return {"inputs": inputs, "outputs": outputs, "available": False, "error": str(e)}

    def set_camera(self, idx):
        """Switch camera live (no restart)."""
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad index"}
        settings.set("camera_index", idx)
        self.engine.request_camera(idx)
        return {"ok": True, "camera_index": idx}

    def camera_driver_settings(self):
        """Open the camera driver's property page (turn off low-light compensation /
        dynamic frame rate there if the camera drops to ~10 fps in dim light)."""
        self.engine.request_driver_settings()
        return {"ok": True}

    def refresh_app(self):
        """Restart the whole backend (engine + overlay) in place — the recovery button."""
        from .engine import CursorBus, Engine
        from .overlay import Overlay
        log.info("refresh_app: restarting backend")
        with self._lock:
            try:
                self.engine.arm(False)
                self.engine.stop()
                self.engine.join(timeout=3.0)
                self.engine.cleanup()
            except Exception:
                log.exception("refresh: engine stop failed")
            try:
                if self.overlay:
                    self.overlay.stop()
                    self.overlay.join(timeout=2.0)
            except Exception:
                log.exception("refresh: overlay stop failed")
            self._engine_started = False
            self.bus = CursorBus()
            self.overlay = Overlay(self.bus)
            self.overlay.start()
            self.engine = Engine(self.bus)
            self.engine.start()
            self._engine_started = True
        log.info("refresh_app: backend restarted")
        return {"ok": True}

    # -- misc ----------------------------------------------------------------
    def open_log(self):
        try:
            os.startfile(LOG_PATH)
            return True
        except Exception:
            return False

    def about(self):
        return {"name": APP_NAME, "version": __version__, "platform": sys.platform}


def run_dev_selftest():
    """Headless smoke: model loads, engine thread runs, no camera required."""
    from .engine import CursorBus, Engine
    bus = CursorBus()
    eng = Engine(bus)
    eng._load_model()
    print("MODEL_LOAD_OK", eng.landmarker is not None)
    print("BACKEND", getattr(eng, "_backend_name", "?"))
    # sonar stack (experimental): sounddevice + bundled portaudio must survive
    # packaging — a missing DLL fails silently at feature-use time otherwise
    try:
        from .sonar import sd as _sd
        n = len(_sd.query_devices()) if _sd is not None else 0
        print("SONAR_STACK_OK", _sd is not None, f"({n} audio devices)")
    except Exception as e:  # noqa: BLE001
        print("SONAR_STACK_OK False", repr(e))
    return 0


def _count_sky_near(cx, cy, box=200):
    """Count sky-orb pixels around (cx, cy) on the COMPOSITED desktop.

    Uses BitBlt with CAPTUREBLT (sees layered windows). Internal state checks
    cannot prove the orb actually renders — the Win11 failure mode where
    UpdateLayeredWindow 'succeeds' but nothing composites is silent.
    """
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    g = ctypes.WinDLL("gdi32", use_last_error=True)
    SRCCOPY = 0x00CC0020
    CAPTUREBLT = 0x40000000

    class BMIH(ctypes.Structure):
        _fields_ = (("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD))

    g.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    g.BitBlt.restype = wintypes.BOOL
    g.CreateCompatibleDC.argtypes = [wintypes.HDC]
    g.CreateCompatibleDC.restype = wintypes.HDC
    g.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    g.CreateCompatibleBitmap.restype = wintypes.HANDLE
    g.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    g.SelectObject.restype = wintypes.HANDLE
    g.GetDIBits.argtypes = [wintypes.HDC, wintypes.HANDLE, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    g.GetDIBits.restype = ctypes.c_int
    u.GetDC.argtypes = [wintypes.HWND]
    u.GetDC.restype = wintypes.HDC

    x0, y0 = int(cx - box // 2), int(cy - box // 2)
    sdc = u.GetDC(None)
    mdc = g.CreateCompatibleDC(sdc)
    bmp = g.CreateCompatibleBitmap(sdc, box, box)
    g.SelectObject(mdc, bmp)
    if not g.BitBlt(mdc, 0, 0, box, box, sdc, x0, y0, SRCCOPY | CAPTUREBLT):
        return 0
    bmi = BMIH()
    bmi.biSize = ctypes.sizeof(BMIH)
    bmi.biWidth = box
    bmi.biHeight = -box
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0
    buf = ctypes.create_string_buffer(box * box * 4)
    if not g.GetDIBits(mdc, bmp, 0, box, buf, ctypes.byref(bmi), 0):
        return 0
    data = buf.raw
    n = 0
    for i in range(0, len(data), 4):
        b, gg, r = data[i], data[i + 1], data[i + 2]
        if b > 180 and 120 < gg < 230 and r < 140:
            n += 1
    return n


def run_probe(seconds=3.0):
    """Interactive-session end-to-end check (no window, no arming).

    Verifies: camera capture, MediaPipe inference, one SendInput mouse move
    round-trip, the layered overlay window lifecycle, and clean shutdown.
    Writes 'PROBE OK' or 'PROBE FAIL <reason>' as the last line.
    """
    import time as _t
    from .engine import CursorBus, Engine, SONAR_BOOT_S
    from . import input_win32 as wi

    ok = []
    fail = []
    _dpi_aware()

    def check(name, fn):
        bus.error = None
        try:
            fn()
            ok.append(name)
            print(f"  ok   {name}")
        except Exception as e:
            fail.append(f"{name}: {e}")
            print(f"  FAIL {name}: {e!r}")
        finally:
            bus.error = None

    print(f"{APP_NAME} probe")
    bus = CursorBus()
    eng = Engine(bus)
    check("model load", eng._load_model)
    check("camera open", lambda: (_ for _ in ()).throw(RuntimeError("no camera"))
          if (setattr(eng, "capture", eng._open_camera(int(settings.get("camera_index")))) or eng.capture is None) else None)

    def sonar_stack():
        from .sonar import sd as _sd
        if _sd is None:
            raise RuntimeError("sounddevice unavailable (portaudio DLL missing)")
        devs = _sd.query_devices()
        if not devs:
            raise RuntimeError("portaudio reports no audio devices")
        print(f"  sonar: sounddevice ok, {len(devs)} audio devices visible")
    check("sonar stack (sounddevice/portaudio)", sonar_stack)

    # Actually START the sonar, not just import it: the stack check above passes
    # in any session where the portaudio DLL is present, which says nothing about
    # whether the tone output and analysis input can really open (sample-rate
    # mismatch, a device held by another app, a driver in a bad state). Run it
    # through the engine's own supervisor so the retry/backoff path is exercised
    # too, then confirm blocks are actually being analysed.
    def sonar_live():
        from .sonar import Sonar
        s = Sonar()
        s.start_async().join(timeout=SONAR_BOOT_S)
        if s.start_error:
            raise RuntimeError(f"sonar would not start: {s.start_error}")
        try:
            deadline = time.time() + 3.0
            while time.time() < deadline and s.diag.get("blocks", 0) < 5:
                time.sleep(0.1)
            d = dict(s.diag)
            if d.get("blocks", 0) < 5:
                raise RuntimeError(f"sonar opened but analysed no blocks ({d})")
            print(f"  sonar: live — {d['blocks']} blocks @ {d.get('sr')} Hz, "
                  f"tone {d.get('tone'):.0f} Hz, carrier +{d.get('carrier_db', 0):.0f} dB "
                  f"over floor, motion {d.get('score', 0):.2f}")
        finally:
            s.stop()
    check("sonar live start (tone out + analysis in)", sonar_live)

    # input round trip — read the cursor fresh each attempt and retry a few
    # times: the user may be moving the mouse or a fullscreen game may be
    # pinning the cursor mid-probe, which is not a SendInput fault
    def input_rt():
        vx, vy, vw, vh = wi.virtual_screen()

        def attempt():
            x0, y0 = wi.cursor_pos()
            tx = min(max(x0 + 60, vx + 2), vx + vw - 3)
            ty = min(max(y0 + 40, vy + 2), vy + vh - 3)
            if (tx, ty) == (x0, y0):
                raise RuntimeError("screen too small to test cursor movement")
            wi.move_absolute(tx, ty)
            _t.sleep(0.25)
            x1, y1 = wi.cursor_pos()
            moved = abs(x1 - tx) + abs(y1 - ty)
            wi.move_absolute(x0, y0)
            if moved > 4:
                if (x1, y1) == (x0, y0):
                    raise RuntimeError("cursor did not move — a fullscreen game or remote tool "
                                       "is holding it (close it and re-run the probe)")
                raise RuntimeError(f"cursor landed off target: want ({tx},{ty}) got ({x1},{y1})")
            if (x1, y1) == (x0, y0):
                raise RuntimeError(f"cursor did not move: ({x0},{y0})")

        last = None
        for _ in range(3):
            try:
                attempt()
                return
            except RuntimeError as e:
                last = e
                _t.sleep(0.35)
        raise last
    check("SendInput round-trip", input_rt)

    # overlay lifecycle + REAL compositing check (pixels on the composited screen)
    def overlay_rt():
        from .overlay import Overlay
        ov = Overlay(bus, fps=30)
        ov.start()
        _t.sleep(1.0)
        if bus.error:
            raise RuntimeError(bus.error)
        with bus.lock:
            bus.armed = True
            bus.dim = False
            bus.position = (300.0, 300.0)
            bus.found = True
        _t.sleep(0.8)
        sky = _count_sky_near(300, 300)
        with bus.lock:
            bus.armed = False
        _t.sleep(0.3)
        ov.stop()
        if sky < 50:
            raise RuntimeError(f"orb not visible on screen (sky_pixels={sky})")
        print(f"  overlay: {sky} orb pixels visible on screen")
    check("overlay lifecycle + visibility", overlay_rt)

    # engine loop: throughput must not depend on the camera's CURRENT rate —
    # virtual cams (Camo) throttle to ~1 fps whenever their source goes idle,
    # which is not an engine fault. The real device was already verified by the
    # camera-open check; here the engine runs on a synthetic 30 fps feed so the
    # number reflects OUR loop (pacing + inference + bookkeeping).
    def engine_rt():
        import numpy as _np
        real_capture = eng.capture

        class _Feed:  # synthetic 30fps source, solid color cycling so frames differ
            def __init__(self):
                self._t = 0.0

            def read(self):
                self._t += 1 / 30.0
                img = _np.zeros((480, 854, 3), dtype=_np.uint8)
                img[:] = int(self._t * 60) % 256
                return True, img

            def isOpened(self):
                return True

            def release(self):
                pass

        eng.capture = _Feed()  # engine reuses a pre-opened capture
        eng.start()
        deadline = _t.time() + 30
        while _t.time() < deadline and bus.frames < 3 and not bus.error:
            _t.sleep(0.2)
        if bus.error:
            raise RuntimeError(bus.error)
        base = bus.frames
        _t.sleep(float(seconds))
        frames = bus.frames - base
        fps, lat = bus.fps, bus.latency_ms
        print(f"  backend: {getattr(eng, '_backend_name', '?')}")
        err = bus.error
        eng.stop()
        eng.cleanup()
        if real_capture is not None:
            try:
                real_capture.release()
            except Exception:
                pass
        if err:
            raise RuntimeError(err)
        if frames < 25:  # paced at 30fps; >=8fps proves the loop is live
            raise RuntimeError(f"only {frames} frames processed in {seconds:.0f}s (synthetic feed)")
        print(f"  frames={frames} in {seconds:.0f}s  fps={fps:.1f} latency={lat:.1f}ms")
    check(f"engine loop ({seconds:.0f}s, synthetic feed)", engine_rt)

    def engine_dup_rt():
        """2.5.1: a REPEATING feed (what a static scene on a virtual cam does)
        must not stall the engine — the duplicate-frame gate once slept
        ~forever on the first repeated frame due to a clock mix."""
        import numpy as _np

        class _RepeatFeed:
            def __init__(self):
                self.n = 0

            def isOpened(self):
                return True

            def read(self):
                self.n += 1
                frame = _np.zeros((48, 64, 3), dtype=_np.uint8)
                k = (self.n // 3) % 32
                frame[8:16, k:k + 8] = 200
                return True, frame

            def set(self, *a):
                pass

            def release(self):
                pass

        bus2 = CursorBus()
        eng2 = Engine(bus2)
        eng2.capture = _RepeatFeed()
        eng2._dedupe = True                  # force the duplicate gate on
        eng2.start()
        t0 = _t.time()
        while _t.time() - t0 < 8 and bus2.frames < 4 and not bus2.error:
            _t.sleep(0.2)
        eng2.stop()
        eng2.cleanup()
        if bus2.error:
            raise RuntimeError(bus2.error)
        if bus2.frames < 4:
            raise RuntimeError(f"duplicate-frame gate stalled the engine ({bus2.frames} frames in 8s)")
        print(f"  repeated feed survived: {bus2.frames} frames processed")
    check("duplicate-frame handling (repeated feed)", engine_dup_rt)

    print(f"PROBE OK {len(ok)} ok, {len(fail)} failed" if not fail
          else "PROBE FAIL " + "; ".join(fail))
    return 0 if not fail else 1


def run_camprobe(index, w, h, fps, seconds):
    """Measure ONE camera mode in this (subprocess) instance and print
    'CAMPROBE <fps>'. Spawned by the engine's camera probe so a driver-level
    crash (access violation) takes down the probe, not the app."""
    import cv2 as _cv2
    # Mirrors engine.CAMERA_MIN_W/H. Duplicated rather than imported: this runs
    # as a bare `--camprobe` subprocess where importing handjob.engine would
    # pull in the model stack and defeat the point of the isolated probe.
    _MIN_W, _MIN_H = 320, 240
    cap = None
    for backend in (_cv2.CAP_DSHOW, _cv2.CAP_ANY):
        try:
            cap = _cv2.VideoCapture(int(index), backend)
            if not cap.isOpened():
                cap.release()
                cap = None
                continue
            try:
                cap.set(_cv2.CAP_PROP_FOURCC, _cv2.VideoWriter_fourcc(*"MJPG"))
            except Exception:
                pass
            cap.set(_cv2.CAP_PROP_FRAME_WIDTH, int(w))
            cap.set(_cv2.CAP_PROP_FRAME_HEIGHT, int(h))
            cap.set(_cv2.CAP_PROP_FPS, int(fps))
            cap.set(_cv2.CAP_PROP_BUFFERSIZE, 1)
            ok, frame = cap.read()
            if ok and frame is not None:
                # The probe must judge the mode the driver ACTUALLY delivered: a
                # held/degenerate stream answers full-rate with a tiny default
                # frame (seen: 64x48), which would otherwise be blessed as a
                # good mode and handed to the engine, where the hand is ~10 px
                # of noise and the landmarks jump. Report the mismatch as a
                # failure so the ladder moves on.
                fh, fw = frame.shape[:2]
                if fw < _MIN_W or fh < _MIN_H:
                    print(f"CAMPROBE FAIL (delivered {fw}x{fh}, below {_MIN_W}x{_MIN_H})")
                    cap.release()
                    return 1
                if (fw, fh) != (int(w), int(h)):
                    print(f"CAMPROBE NOTE asked {w}x{h} delivered {fw}x{fh}")
            if not ok:
                cap.release()
                cap = None
                continue
            break
        except Exception:
            cap = None
    if cap is None:
        print("CAMPROBE FAIL")
        return 1
    t0 = time.perf_counter()
    n = 0
    deadline = t0 + float(seconds)
    while time.perf_counter() < deadline:
        try:
            ok, _ = cap.read()
        except Exception:
            ok = False
        if ok:
            n += 1
        else:
            time.sleep(0.01)
    dt = time.perf_counter() - t0
    cap.release()
    if n < 3 or dt <= 0:
        print("CAMPROBE FAIL")
        return 1
    print(f"CAMPROBE {n / dt:.2f}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("--dev", action="store_true", help="serve UI in a local browser instead of the app window")
    parser.add_argument("--selftest", action="store_true", help="headless model load + exit")
    parser.add_argument("--probe", action="store_true", help="end-to-end hardware check (no window, no arming)")
    parser.add_argument("--camprobe", nargs=5, metavar=("INDEX", "W", "H", "FPS", "SECONDS"),
                        help="internal: measure one camera mode, print CAMPROBE <fps>")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)
    log.info("%s %s starting (frozen=%s)", APP_NAME, __version__, getattr(sys, "frozen", False))

    # fair GIL scheduling: the engine thread must never starve the UI thread
    try:
        sys.setswitchinterval(0.001)
    except Exception:
        pass

    if not (args.probe or args.camprobe):
        # single instance per user session: a second launch must not fight for
        # the camera. Probe modes (--probe, --camprobe) are exempt: the engine
        # spawns --camprobe subprocesses while the app itself is running.
        import ctypes as _ct
        _mutex = _ct.windll.kernel32.CreateMutexW(None, False, "HandJob3000_SingleInstance")
        if not _mutex or _ct.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            log.info("another instance is already running — exiting")
            return 0

    if args.selftest:
        return run_dev_selftest()
    if args.probe:
        return run_probe()
    if args.camprobe:
        return run_camprobe(*args.camprobe)

    _dpi_aware()
    api = Api()
    api.start()

    import webview
    ui = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "ui", "index.html")
    if args.dev:
        import webbrowser
        webbrowser.open("file:///" + ui.replace("\\", "/"))

    # size to the actual work area (laptops vary; 1180x780 must never hang off-screen)
    width, height = 1180, 780
    try:
        import ctypes as _ct
        from ctypes import wintypes as _wt
        rect = _wt.RECT()
        if _ct.windll.user32.SystemParametersInfoW(0x0030, 0, _ct.byref(rect), 0):
            width = max(900, min(1180, rect.right - rect.left - 60))
            height = max(620, min(780, rect.bottom - rect.top - 60))
    except Exception:
        pass
    window = webview.create_window(
        APP_NAME,
        ui,
        js_api=api,
        width=width,
        height=height,
        min_size=(900, 600),
        background_color="#F7F7F5",
    )
    api._window = window            # lets the model importer open a file picker
    try:
        webview.start(debug=args.dev)
    finally:
        api.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
