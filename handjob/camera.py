"""camera.py — threaded, latest-frame-wins camera grabber (2.6).

Why this exists.  Until 2.5 the engine thread did `capture.read()` itself, then
inference, drawing, JPEG encoding, pacing sleeps, and only THEN went back to
`read()`.  Webcam drivers (DirectShow in particular) keep a small queue of
frames, so every time the loop took longer than one camera interval (a GC
pause, a preview encode, the UI thread holding the GIL) the queue filled and
the loop then chewed through STALE frames at full speed: the cursor lagged by
a few frames, then caught up in a burst.  The frame's "arrival" timestamp
(taken after read() returned) was wrong for those frames too, which is
exactly the dt/velocity noise that shows up as jitter.

Now a dedicated thread does nothing but `read()` -> stamp -> publish.

  * the stamp is `time.perf_counter()` taken the instant read() returns, i.e. as
    close to the true capture time as user space can get; it is monotonic and
    high-resolution (time.time() on Windows/Python <= 3.12 ticks at ~15.6 ms)
  * only the NEWEST frame is kept; a slow consumer drops frames instead of
    queueing them, so latency can never grow
  * MJPG decode (the expensive part of read()) overlaps with inference: both
    release the GIL, so this is real pipeline parallelism, not just tidiness
  * reconnecting (stall, unplug, camera switch, fps change) never blocks the
    consumer thread; it keeps getting `None` from get() until frames resume
  * unique-frame accounting (virtual cams / low-light auto-exposure repeat
    frames) is a few microseconds on a strided sample — it only WARNS now.
    Re-opening the camera never fixes a dim room, it just drops tracking for
    seconds, so the old reopen-on-low-fps watchdogs are gone.

The module is pure python + numpy; the camera itself comes from `open_fn`
(cv2 in the app, a fake in the tests).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

import numpy as np

log = logging.getLogger("handjob.camera")

STALL_S = 2.0            # no frame for this long -> reopen
SIG_STRIDE = 24          # pixel stride of the content signature (a ~30x54 sample at 720p)
NEW_FRAME_DELTA = 0.35   # mean abs difference above this = a genuinely new frame
STATS_WINDOW_S = 2.0


class FrameGrabber(threading.Thread):
    """Reads one camera on its own thread and publishes only the newest frame.

    open_fn(index) -> capture-like object (read() -> (ok, frame); release(); optional
    set()) or None when the camera could not be opened.  It runs on the grabber
    thread, so a slow/hanging open never blocks the engine.
    """

    STALL_S = STALL_S

    def __init__(self, open_fn, index=0, clock=time.perf_counter, name="HJ3-Camera"):
        super().__init__(daemon=True, name=name)
        self._open_fn = open_fn
        self._clock = clock
        self.index = int(index)
        self._stop_ev = threading.Event()
        self._wake = threading.Event()
        self._cond = threading.Condition()
        self._frame = None
        self._t = 0.0
        self._seq = 0
        self._cap = None
        # requests from other threads, handled between reads
        self._req_index = None
        self._req_reopen = False
        self._req_dialog = False
        # health
        self.connected = False
        self.error = None            # human-readable, None when fine
        self.frames = 0
        self.dropped = 0             # frames published but never consumed
        self.reopens = 0
        self.size = None             # (w, h) of the last frame
        self.brightness = 128.0      # EMA of the mean luma of a strided sample (0..255)
        self._consumed_seq = 0
        self._sig_prev = None
        self._hist = deque(maxlen=400)   # (t, is_new) of recent reads

    # ------------------------------------------------------------ consumer API
    def get(self, last_seq=0, timeout=0.25):
        """Newest frame with seq > last_seq as (frame, t_arrival, seq), or None on timeout.

        The array is shared with nobody who writes to it (the grabber never touches a frame after
        publishing it) — treat it as read-only and cv2.resize/flip into new arrays."""
        with self._cond:
            if self._seq <= last_seq and not self._stop_ev.is_set():
                self._cond.wait(timeout)
            if self._seq <= last_seq or self._frame is None:
                return None
            seq = self._seq
            frame, t = self._frame, self._t
            self._consumed_seq = seq
            return frame, t, seq

    def request_index(self, index):
        """Switch to another camera (non-blocking)."""
        self._req_index = int(index)
        self._wake.set()

    def request_reopen(self):
        """Reopen the current camera (e.g. the fps setting changed)."""
        self._req_reopen = True
        self._wake.set()

    def request_driver_dialog(self):
        """Open the camera driver's own property page on the grabber thread (DirectShow)."""
        self._req_dialog = True
        self._wake.set()

    def stop(self, timeout=1.5):
        self._stop_ev.set()
        self._wake.set()
        with self._cond:
            self._cond.notify_all()
        if self.is_alive() and threading.current_thread() is not self:
            self.join(timeout)

    def rates(self):
        """(reads_per_s, new_frames_per_s) over the last ~2 s, or (None, None) when too little data."""
        h = list(self._hist)
        if len(h) < 10:
            return None, None
        t_end = h[-1][0]
        h = [x for x in h if t_end - x[0] <= STATS_WINDOW_S]
        span = h[-1][0] - h[0][0]
        if len(h) < 10 or span < 0.8:
            return None, None
        return (len(h) - 1) / span, sum(1 for _, new in h[1:] if new) / span

    # ------------------------------------------------------------------ thread
    def _publish(self, frame, t):
        with self._cond:
            if self._seq > self._consumed_seq:
                self.dropped += 1        # the previous frame was never picked up
            self._frame, self._t = frame, t
            self._seq += 1
            self.frames += 1
            self._cond.notify_all()

    def _signature(self, frame):
        """Strided colour sample: cheap fingerprint + brightness in one go."""
        try:
            s = frame[::SIG_STRIDE, ::SIG_STRIDE]
            sig = s.astype(np.int16)
            mean = float(sig.mean())
            self.brightness += 0.05 * (mean - self.brightness)
            return sig - int(mean)
        except Exception:
            return None

    def _close(self):
        cap, self._cap = self._cap, None
        self.connected = False
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass

    def _handle_requests(self):
        if self._req_index is not None:
            idx, self._req_index = self._req_index, None
            if idx != self.index:
                log.info("camera switch requested -> %s", idx)
            self.index = idx
            self._close()
            self.reopens += 1
        if self._req_reopen:
            self._req_reopen = False
            log.info("camera reopen requested")
            self._close()
            self.reopens += 1
        if self._req_dialog:
            self._req_dialog = False
            if self._cap is not None:
                try:
                    import cv2
                    self._cap.set(cv2.CAP_PROP_SETTINGS, 1)      # modal; returns when closed
                except Exception:
                    log.exception("camera driver settings dialog failed")

    def run(self):
        backoff = 0.25
        fail_since = None
        while not self._stop_ev.is_set():
            self._handle_requests()
            if self._cap is None:
                try:
                    cap = self._open_fn(self.index)
                except Exception:
                    log.exception("camera open raised")
                    cap = None
                if self._stop_ev.is_set():
                    if cap is not None:
                        try:
                            cap.release()
                        except Exception:
                            pass
                    break
                if cap is None:
                    self.error = f"camera {self.index} busy or unavailable — is another app using it?"
                    self._wake.wait(backoff)
                    self._wake.clear()
                    backoff = min(2.0, backoff * 1.6)
                    continue
                self._cap = cap
                self.connected = True
                self.error = None
                backoff = 0.25
                fail_since = None
                self._sig_prev = None
                log.info("camera %s open", self.index)
            try:
                ok, frame = self._cap.read()
            except Exception:
                ok, frame = False, None
            t = self._clock()                # arrival stamp: the instant read() returned
            if not ok or frame is None:
                if fail_since is None:
                    fail_since = t
                elif t - fail_since > self.STALL_S:
                    log.warning("camera %s stalled %.1fs — reopening", self.index, t - fail_since)
                    self._close()
                    self.reopens += 1
                    fail_since = None
                    self.error = f"camera {self.index} stopped delivering frames — reconnecting"
                    continue
                self._wake.wait(0.02)
                self._wake.clear()
                continue
            fail_since = None
            self.size = (frame.shape[1], frame.shape[0])
            sig = self._signature(frame)
            new = True
            if sig is not None:
                prev, self._sig_prev = self._sig_prev, sig
                if prev is not None and prev.shape == sig.shape:
                    new = float(np.abs(sig - prev).mean()) > NEW_FRAME_DELTA
            self._hist.append((t, new))
            self._publish(frame, t)
        self._close()
