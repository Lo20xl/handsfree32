"""preview.py — the UI preview, rendered and JPEG-encoded off the engine thread (2.6).

Until 2.5 the engine drew the skeleton, JPEG-encoded the frame and base64-ed it
inline, 30 times a second, on the same thread that tracks the hand: every frame's
tracking waited for the previous frame's preview.  Now the engine hands over a
cheap snapshot (a reference to the processed frame + 21 points per hand) and moves
on; this worker draws, encodes and publishes at <= max_fps.  Jobs are coalesced —
if the worker is busy the OLDEST pending job is replaced, never queued — and the
preview is smaller (<= 480 px wide, ~15 fps): the UI shows a 320-px thumbnail, and
every byte crosses the webview bridge as base64.
"""
from __future__ import annotations

import logging
import threading
import time

import cv2
import numpy as np

log = logging.getLogger("handjob.preview")

SKY_BGR = (248, 189, 56)
WHITE_BGR = (255, 255, 255)
GREY_BGR = (110, 116, 128)
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
)


def render_preview(mode, frame, hands, active, stable, max_width=480):
    """BGR canvas for the UI. `hands` = [[(x, y) * 21], ...] normalized; `stable` replaces the
    active hand's points with the stabilized ones."""
    h, w = frame.shape[:2]
    if w > max_width:
        h, w = max(2, int(round(h * max_width / float(w)))), max_width
        small = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA) if mode == "camera" else None
    else:
        small = frame if mode == "camera" else None
    canvas = np.zeros((h, w, 3), dtype=np.uint8) if mode != "camera" else small.copy()
    lw = max(1, w // 240)
    dot = max(2, w // 160)
    for hi, hand in enumerate(hands):
        primary = hi == active
        pts = hand
        if primary and stable is not None and len(stable) == len(hand):
            pts = stable
        pts = [(int(p[0] * w), int(p[1] * h)) for p in pts]
        color = SKY_BGR if primary else GREY_BGR
        for a, b in HAND_CONNECTIONS:
            cv2.line(canvas, pts[a], pts[b], color, lw + 1 if primary else 1, cv2.LINE_AA)
        for p in pts:
            cv2.circle(canvas, p, dot, WHITE_BGR if primary else color, -1, cv2.LINE_AA)
        if primary:
            for a, b in ((4, 12), (4, 16)):            # thumb -> middle / ring pinch links
                cv2.line(canvas, pts[a], pts[b], SKY_BGR, 1, cv2.LINE_AA)
    return canvas


class PreviewWorker(threading.Thread):
    def __init__(self, sink, max_fps=15.0, quality=55, max_width=480):
        super().__init__(daemon=True, name="HJ3-Preview")
        self._sink = sink                      # sink(jpeg_bytes)
        self.min_interval = 1.0 / max(1.0, float(max_fps))
        self._params = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
        self.max_width = int(max_width)
        self._cv = threading.Condition()
        self._job = None
        self._stop_ev = threading.Event()
        self._last = 0.0
        self.encoded = 0
        self.last_ms = 0.0
        self._fail_logged = False

    def due(self, now=None):
        """Cheap gate for the engine: is it worth building a job right now?"""
        return ((now if now is not None else time.perf_counter()) - self._last) >= self.min_interval

    def submit(self, mode, frame, hands, active, stable):
        """Non-blocking; replaces any job still waiting."""
        with self._cv:
            self._job = (mode, frame, hands, active, stable)
            self._cv.notify()

    def stop(self):
        self._stop_ev.set()
        with self._cv:
            self._cv.notify_all()

    def run(self):
        while not self._stop_ev.is_set():
            with self._cv:
                if self._job is None:
                    self._cv.wait(0.25)
                job, self._job = self._job, None
            if job is None:
                continue
            wait = self.min_interval - (time.perf_counter() - self._last)
            if wait > 0:
                time.sleep(wait)
            with self._cv:                      # a newer job may have arrived while we slept
                if self._job is not None:
                    job, self._job = self._job, None
            t0 = time.perf_counter()
            try:
                canvas = render_preview(*job, max_width=self.max_width)
                ok, jpg = cv2.imencode(".jpg", canvas, self._params)
                if ok:
                    self._sink(jpg.tobytes())
                    self.encoded += 1
                elif not self._fail_logged:
                    self._fail_logged = True
                    log.warning("preview encode failed")
            except Exception:
                if not self._fail_logged:
                    self._fail_logged = True
                    log.exception("preview render failed")
            self._last = time.perf_counter()
            self.last_ms = (self._last - t0) * 1000.0
