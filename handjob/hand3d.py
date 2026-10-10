"""hand3d.py - 3D pinch measurement, debounced pose, clutch re-anchoring, telemetry.

Why 3D: a 2D "tip distance / 2D palm length" ratio reports a click whenever the thumb
merely OVERLAPS the middle/ring fingertip in the image (the depth gap is invisible),
and its scale shrinks when the palm tilts. MediaPipe's `hand_world_landmarks` are
metric 3D (meters, origin at the hand centre), so distances and palm length do not
depend on rotation or perspective.  Depth is the noisiest axis of a single camera, so
the 3D ratio is smoothed (time-constant EMA), cross-checked against the image (a pair
that is clearly apart in the image can never be "pinching"), and the threshold should
be calibrated per user (calibrate_pinch).

Pose stays 2D (your classify_pose): measured on noisy synthetic hands, a 3D
finger-straightness test flickered MORE than the 2D test, so 3D is used only where
2D is actually wrong (pinch).  PoseTracker makes the pose stable instead.

Pure python + stdlib.  `python hand3d.py` runs the self-test.
"""
from __future__ import annotations

import math
from collections import Counter, deque
from typing import Optional, Sequence, Tuple

__all__ = ["PinchMeter3D", "PoseTracker", "EdgeStabilizer", "calibrate_pinch", "reanchor",
           "os_cursor_pos", "Telemetry"]

WRIST, THUMB_TIP, MIDDLE_MCP, MIDDLE_TIP, RING_TIP = 0, 4, 9, 12, 16


def _xyz(p) -> Tuple[float, float, float]:
    try:
        return p.x, p.y, p.z
    except AttributeError:
        return p[0], p[1], p[2]


def _xy2d(a, b) -> float:
    try:
        return math.hypot(a.x - b.x, a.y - b.y)
    except AttributeError:
        return math.hypot(a[0] - b[0], a[1] - b[1])


class PinchMeter3D:
    """thumb-tip <-> middle-tip / ring-tip distance over 3D palm length, smoothed.

    update(world, image, now) -> (l_ratio, r_ratio): feed these to ClickRefiner and
    to disambiguate_pinches() instead of the 2D ratios.  `world` = result.hand_world_landmarks[i],
    `image` = result.hand_landmarks[i] (same hand index).  Falls back to the 2D ratio when
    the world landmarks are missing/implausible (palm length outside 3..25 cm).
    """

    def __init__(self, tau: float = 0.035, veto_2d: float = 2.0, thr_hint: float = 0.28) -> None:
        self.tau, self.veto_2d, self.thr_hint = tau, veto_2d, thr_hint
        self.source = "3d"
        self.reset()

    def reset(self) -> None:
        self._l: Optional[float] = None
        self._r: Optional[float] = None
        self._t: Optional[float] = None

    def update(self, world, image, now: float) -> Tuple[float, float]:
        s2 = max(1e-4, _xy2d(image[WRIST], image[MIDDLE_MCP]))
        l2 = _xy2d(image[THUMB_TIP], image[MIDDLE_TIP]) / s2
        r2 = _xy2d(image[THUMB_TIP], image[RING_TIP]) / s2
        l, r = l2, r2
        self.source = "2d"
        if world is not None:
            w0, w9 = _xyz(world[WRIST]), _xyz(world[MIDDLE_MCP])
            palm = math.dist(w0, w9)
            if 0.03 < palm < 0.25:
                th = _xyz(world[THUMB_TIP])
                l = math.dist(th, _xyz(world[MIDDLE_TIP])) / palm
                r = math.dist(th, _xyz(world[RING_TIP])) / palm
                lim = self.veto_2d * self.thr_hint                  # clearly apart in the image => not touching
                if l2 > lim:
                    l = max(l, l2)
                if r2 > lim:
                    r = max(r, r2)
                self.source = "3d"
        if self._t is None or now - self._t > 0.25 or now <= self._t:
            self._l, self._r = l, r
        else:
            a = 1.0 - math.exp(-min(0.1, now - self._t) / self.tau)
            self._l += a * (l - self._l)
            self._r += a * (r - self._r)
        self._t = now
        return self._l, self._r


class PoseTracker:
    """Debounce the raw per-frame pose ('point' | 'scroll' | 'idle').

    A pose change needs >= min_frames consecutive agreeing frames AND dwell seconds:
    entering point 0.06 s, leaving it 0.10 s, and while a button is held leaving 'point'
    needs 0.30 s - one bad frame can no longer halt the cursor or drop a drag.
    """

    def __init__(self, dwell_enter: float = 0.06, dwell_leave: float = 0.10,
                 dwell_hold: float = 0.30, min_frames: int = 2) -> None:
        self.dwell_enter, self.dwell_leave, self.dwell_hold = dwell_enter, dwell_leave, dwell_hold
        self.min_frames = min_frames
        self.pose = "idle"
        self.reset()

    def reset(self) -> None:
        self.pose = "idle"
        self._cand: Optional[str] = None
        self._t0 = 0.0
        self._n = 0
        self._last = None

    def update(self, raw: str, now: float, holding: bool = False) -> str:
        if self._last is not None and now - self._last > 0.4:      # tracking gap: start over
            self._cand = None
        self._last = now
        if raw == self.pose:
            self._cand = None
            return self.pose
        if raw != self._cand:
            self._cand, self._t0, self._n = raw, now, 0
        self._n += 1
        if holding and self.pose == "point":
            need = self.dwell_hold
        else:
            need = self.dwell_enter if raw == "point" else self.dwell_leave
        if self._n >= self.min_frames and now - self._t0 >= need:
            self.pose, self._cand = raw, None
        return self.pose


class EdgeStabilizer:
    """Freeze cursor input while the aim point sits in the frame's edge margin.

    As the hand starts leaving the frame, MediaPipe landmarks get noisy (part
    of the hand cropped, depth ambiguous) — the raw aim point jitters by
    several % of the frame per frame, which the cursor shows as violent
    shaking near the screen borders. Inside `margin` the engine keeps feeding
    the LAST stable aim point downstream instead; a small release band
    (margin + `release`) provides hysteresis so grazing the line never
    chatters the hold on/off.
    """

    def __init__(self, margin: float = 0.04, release: float = 0.02) -> None:
        self.margin = margin
        self.release = release
        self.holding = False

    def reset(self) -> None:
        self.holding = False

    def update(self, x: float, y: float) -> bool:
        """Feed the normalized aim point; True = at edge, keep the previous position."""
        m = min(0.2, max(0.0, self.margin) + (self.release if self.holding else 0.0))
        self.holding = (x < m) or (x > 1.0 - m) or (y < m) or (y > 1.0 - m)
        return self.holding


def _pct(v: Sequence[float], q: float) -> Optional[float]:
    s = sorted(v)
    return s[min(len(s) - 1, max(0, int(q * (len(s) - 1) + 0.5)))] if s else None


def calibrate_pinch(open_ratios: Sequence[float], closed_ratios: Sequence[float],
                    frac: float = 0.25, lo: float = 0.15, hi: float = 0.36) -> Optional[float]:
    """Per-user enter threshold from two ~1 s captures of PinchMeter3D output while the user
    (a) holds the fingers apart in the pointing pose, (b) pinches thumb+middle firmly.
    Threshold sits `frac` of the way from the (worst) closed value to the (nearest) open value.
    Returns None when the two captures are not clearly separated (redo the capture)."""
    o, c = _pct(open_ratios, 0.2), _pct(closed_ratios, 0.9)
    if o is None or c is None or o - c < 0.2:
        return None
    return min(hi, max(lo, c + frac * (o - c)))


def reanchor(mapper, hx: float, hy: float, cursor_xy: Tuple[float, float],
             screen_w: float, screen_h: float) -> None:
    """Pick-up-the-mouse semantics for TravelMapper: when pointing (re)starts, shift the
    box so the hand's CURRENT position maps to the cursor's CURRENT position (no jump).
    Stop calling mapper.update_center() while pointing - a fixed mapping is what makes
    the cursor predictable; the clutch (open palm) is how the user re-positions."""
    span = mapper.span
    nx = cursor_xy[0] / max(1.0, screen_w - 1.0)
    ny = cursor_xy[1] / max(1.0, screen_h - 1.0)
    mapper.center = [hx - span * (nx - 0.5), hy - span * (ny - 0.5)]


def os_cursor_pos() -> Optional[Tuple[float, float]]:
    """Current OS cursor position (Windows), or None."""
    try:
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return float(pt.x), float(pt.y)
    except Exception:
        pass
    return None


class Telemetry:
    """Record ~20 s of real use, then print summary(): shows whether the problem is the
    camera loop (fps/interval), inference time, pose flicker, noisy pinch ratios, or the
    emitter thread being starved (late ticks)."""

    def __init__(self, maxlen: int = 4000) -> None:
        self.f: deque = deque(maxlen=maxlen)
        self.ev: list = []

    def frame(self, now: float, infer_ms: float, raw_pose: str, pose: str, l: float, r: float,
              hold: bool = False) -> None:
        self.f.append((now, infer_ms, raw_pose, pose, l, r, hold))

    def event(self, now: float, name: str) -> None:
        self.ev.append((now, name))

    def summary(self, motion=None) -> str:
        f = list(self.f)
        if len(f) < 3:
            return "telemetry: not enough frames"
        dur = f[-1][0] - f[0][0]
        iv = sorted((b[0] - a[0]) * 1000.0 for a, b in zip(f, f[1:]))
        inf = sorted(x[1] for x in f)
        raw_flips = sum(1 for a, b in zip(f, f[1:]) if a[2] != b[2])
        pose_flips = sum(1 for a, b in zip(f, f[1:]) if a[3] != b[3])
        pts = [x for x in f if x[3] == "point"]
        holds = sum(1 for x in f if len(x) > 6 and x[6])
        out = [f"frames {len(f)} in {dur:.1f}s = {len(f) / max(dur, 1e-6):.1f} fps | "
               f"interval ms p50 {_pct(iv, .5):.0f} p95 {_pct(iv, .95):.0f} max {iv[-1]:.0f} | "
               f"inference ms p50 {_pct(inf, .5):.0f} p95 {_pct(inf, .95):.0f}",
               f"pose flips/s: raw {raw_flips / dur:.2f} -> stable {pose_flips / dur:.2f}"
               + (f" | edge-hold {holds / len(f):.0%} of frames" if holds else "")]
        if pts:
            for name, idx in (("L(thumb+middle)", 4), ("R(thumb+ring)", 5)):
                v = [x[idx] for x in pts]
                out.append(f"pinch {name} while pointing: p5 {_pct(v, .05):.2f} p50 {_pct(v, .5):.2f} p95 {_pct(v, .95):.2f}")
        if self.ev:
            out.append("events: " + ", ".join(f"{k} x{n}" for k, n in Counter(n for _, n in self.ev).items()))
        if motion is not None:
            st = motion.stats()
            out.append(f"emitter: {st['ticks']} ticks, {st['late']} late (>2 periods), worst gap {st['max_gap_ms']} ms")
        return "\n".join(out)


# =============================================================================
# self-test:  python hand3d.py     (synthetic hands: validates the LOGIC, not your camera)
# =============================================================================
def _selftest() -> None:
    import random
    import numpy as np

    rnd = random.Random(11)

    class LM:
        __slots__ = ("x", "y", "z")

        def __init__(self, x, y, z):
            self.x, self.y, self.z = x, y, z

    MCP = {1: (0.028, 0.085), 2: (0.005, 0.090), 3: (-0.017, 0.085), 4: (-0.036, 0.075)}
    SEG = {1: (0.040, 0.025, 0.022), 2: (0.045, 0.028, 0.024), 3: (0.042, 0.026, 0.023), 4: (0.032, 0.020, 0.020)}

    def hand(curl):                                    # (21,3) metres, palm in xy
        P = np.zeros((21, 3))
        P[1], P[2], P[3], P[4] = (0.022, 0.012, 0.004), (0.034, 0.035, 0.008), (0.040, 0.055, 0.012), (0.044, 0.073, 0.014)
        for f in (1, 2, 3, 4):
            b, pos, ang = 5 + (f - 1) * 4, np.array([*MCP[f], 0.0]), 0.0
            P[b] = pos
            for k, (flex, L) in enumerate(zip((80, 100, 70), SEG[f])):
                ang += math.radians(flex) * curl.get(f, 0.0)
                pos = pos + np.array([0.0, math.cos(ang), -math.sin(ang)]) * L
                P[b + 1 + k] = pos
        return P - P[[0, 5, 9, 13, 17]].mean(axis=0)

    def rot(rx, ry, rz):
        cx, sx, cy, sy, cz, sz = (f(a) for a in (rx, ry, rz) for f in (math.cos, math.sin))
        return (np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]) @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
                @ np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]]))

    POINT = {1: 0.0, 2: 0.9, 3: 0.95, 4: 0.95}

    def stream(kind, n=400, thumb_to=12, sep=0.04, sxy=0.003, zmul=2.5):
        """Noisy world+image landmarks, hand tilted randomly; thumb touching / hovering in front of a finger."""
        R0 = [rnd.uniform(-30, 30), rnd.uniform(-30, 30), rnd.uniform(-15, 15)]
        out = []
        for _ in range(n):
            R = rot(*(math.radians(a + rnd.gauss(0, 1.5)) for a in R0))
            Pc = (R @ (hand(POINT) @ np.diag([1.0, -1.0, -1.0]).T).T).T
            tgt = Pc[thumb_to]
            if kind == "touch":
                tip = tgt + np.array([0.012 + rnd.gauss(0, .002), rnd.gauss(0, .002), rnd.gauss(0, .003)])
            elif kind == "front":
                tip = tgt + np.array([rnd.gauss(0, .002), rnd.gauss(0, .002), -sep])
            else:                                      # open: thumb out to the side
                tip = Pc[1] + np.array([0.06, 0.0, 0.0])
            Pc[4] = tip
            Pc[2], Pc[3] = Pc[1] + (tip - Pc[1]) * 0.4, Pc[1] + (tip - Pc[1]) * 0.75
            clean = Pc.copy()
            Pc = Pc + np.array([[rnd.gauss(0, sxy), rnd.gauss(0, sxy), rnd.gauss(0, sxy * zmul)] for _ in range(21)])
            Z = 0.45 + Pc[:, 2]
            world = [LM(*p) for p in Pc]
            image = [LM(0.5 + 1.4 * p[0] / z, 0.5 + 1.4 * p[1] / z, 0.0) for p, z in zip(clean, 0.45 + clean[:, 2])]
            image = [LM(p.x + rnd.gauss(0, .003), p.y + rnd.gauss(0, .003), 0.0) for p in image]
            out.append((world, image))
        return out

    def ratios(frames, thumb_idx=0):
        pm, res, legacy = PinchMeter3D(), [], []
        for i, (w, im) in enumerate(frames):
            l, r = pm.update(w, im, i / 30.0)
            res.append(l)
            s2 = _xy2d(im[WRIST], im[MIDDLE_MCP])
            legacy.append(_xy2d(im[THUMB_TIP], im[MIDDLE_TIP]) / s2)           # what the 2D code feeds today
        return np.array(res), np.array(legacy)

    THR = 0.28
    r_t, _ = ratios(stream("touch"))
    r_f, l_f = ratios(stream("front", sep=0.04))
    r_o, _ = ratios(stream("open"))
    assert (r_t < THR).mean() > 0.95 and (r_t > 1.25 * THR).mean() < 0.02, ((r_t < THR).mean(), (r_t > 1.25 * THR).mean())
    assert (r_f < THR).mean() < 0.05, f"3D false-click frames {(r_f < THR).mean():.1%}"
    assert (l_f < 0.35).mean() > 0.95, "sanity: the 2D ratio should be fooled by the overlap"
    assert np.median(r_o) > 0.6
    print(f"3D pinch : real touch below thr {(r_t < THR).mean():.0%}, thumb 4 cm IN FRONT of the finger -> "
          f"false-click frames 3D {(r_f < THR).mean():.1%} vs 2D {(l_f < 0.35).mean():.0%}; open hand median {np.median(r_o):.2f}")

    # fallback when world landmarks are missing
    w, im = stream("touch", n=1)[0]
    pm = PinchMeter3D()
    pm.update(None, im, 0.0)
    assert pm.source == "2d"

    # calibration
    thr = calibrate_pinch(list(r_o), list(r_t))
    assert thr is not None and 0.15 <= thr <= 0.36 and np.percentile(r_t, 90) < thr < np.percentile(r_o, 20), thr
    assert calibrate_pinch([0.4] * 30, [0.3] * 30) is None
    print(f"calibrate: threshold {thr:.2f} from open/closed captures; ambiguous capture rejected")

    # pose debounce
    pt = PoseTracker()
    seq = ["idle"] * 3 + ["point"] * 6 + ["idle"] + ["point"] * 6 + ["scroll"] + ["point"] * 4 + ["idle"] * 6 + ["point"] * 4
    poses = [pt.update(p, 1.0 + i / 30.0) for i, p in enumerate(seq)]
    assert poses[4] == "idle" and poses[5] == "point"             # entering point: 2 frames + 0.06 s
    assert poses[9] == "point" and poses[16] == "point"           # 1-frame glitches ignored
    assert poses[22] == "point" and poses[24] == "idle" and poses[-1] == "point"
    flips_raw = sum(a != b for a, b in zip(seq, seq[1:]))
    flips_st = sum(a != b for a, b in zip(poses, poses[1:]))
    pt = PoseTracker()
    for i in range(10):
        pt.update("point", i / 30.0)
    held = [pt.update("idle", 1.0 + i / 30.0, holding=True) for i in range(14)]
    assert held[0] == "point" and held[8] == "point" and held[-1] == "idle", held   # 0.30 s needed while holding
    print(f"pose     : raw flips {flips_raw} -> stable {flips_st}; button held needs 0.30 s of non-point to drop")

    # re-anchor: hand position maps onto the existing cursor (no jump on engage)
    class TravelMapper:                               # same maths as gestures.TravelMapper.to_screen
        def __init__(self, sens=0.6):
            self.sensitivity, self.center = sens, None

        @property
        def span(self):
            return 0.92 - 0.58 * min(1.0, max(0.1, self.sensitivity))

        def to_screen(self, x, y, w, h):
            span, (cx, cy) = self.span, self.center
            nx = min(1.0, max(0.0, (x - (cx - span / 2)) / span))
            ny = min(1.0, max(0.0, (y - (cy - span / 2)) / span))
            return nx * (w - 1), ny * (h - 1)

    tm = TravelMapper()
    for hx, hy, cur in ((0.30, 0.60, (1000.0, 500.0)), (0.72, 0.35, (200.0, 900.0)), (0.5, 0.5, (1919.0, 0.0))):
        reanchor(tm, hx, hy, cur, 1920, 1080)
        sx, sy = tm.to_screen(hx, hy, 1920, 1080)
        assert abs(sx - cur[0]) < 1e-6 and abs(sy - cur[1]) < 1e-6, (sx, sy, cur)
    print("reanchor : hand maps exactly onto the current cursor at engage")

    # telemetry smoke
    tel = Telemetry()
    for i in range(120):
        tel.frame(i / 30.0, 18.0 + (i % 7), "point" if i % 40 else "idle", "point", 0.5 + 0.01 * (i % 5), 0.9)
    tel.event(1.0, "left_down")
    assert "fps" in tel.summary() and "left_down" in tel.summary()
    print("all hand3d self-tests passed")


if __name__ == "__main__":
    _selftest()
