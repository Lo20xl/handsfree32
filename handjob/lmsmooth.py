"""lmsmooth.py — landmark-level stabilization (2.2): the anti-jitter core.

MediaPipe landmarks jitter by several % of the frame at rest, and SPIKE
(teleport / finger-swap / palm-scale flip, 10-50% jumps) when the tracker
briefly loses lock. Cursor motion has its own smoothing downstream, but pose
classification and the pinch metric consume the RAW landmark stream — one
spiky frame flips the pose ("freaks out") or fires a phantom pinch.

This module cleans the stream itself, per hand, before anything else reads it:

  * adaptive EMA (1€ filter): cutoff grows with landmark speed — heavy
    smoothing at rest (kills jitter), light smoothing mid-motion (no lag),
    effectively raw during fast gestures.
  * spike gate: a single-frame jump larger than a palm-relative budget is
    pulled back toward the filtered position, so a lost-lock teleport never
    reaches pose/pinch code. A genuine fast swipe moves under the budget.
  * palm-scale guard: if the palm length itself jumps >40% in one frame the
    whole frame is a tracker glitch (z-flip) — it is rejected outright. A
    scale change that PERSISTS across consecutive frames is not a glitch but
    the hand genuinely changing apparent size (leaned toward/away, rotated):
    the filter re-seeds onto it, so the cursor can never freeze forever.

All budgets are expressed in PALM LENGTH units, so the same parameters work
for image-space (normalized) and world-space (metres) landmarks.

2.6: two outputs.  `process()` returns the SMOOTHED landmarks (pose / pinch).
`self.gated` holds the same frame after the spike gate only — NO smoothing.
The cursor aim point reads `gated`: the cursor's own noise-adaptive stage
(motion.py) is the single place where the aim is smoothed.  Filtering the aim
here as well (the old 0.5 Hz / beta 2 chain) stacked two low-pass stages and
cost ~100 ms of lag on slow, precise movements.  The retuned BETA also halves
the lag of the pinch metric during the (fast) finger-closing motion.
"""

from __future__ import annotations

import math

N_LMS = 21
WRIST, MIDDLE_MCP = 0, 9

# 1€ filter defaults (tuned for 30-60 fps landmark streams; measured on
# synthetic jitter+swipe: rest jitter ~13% of raw variance, swipe lag ~0.1 palm)
MIN_CUTOFF = 0.8    # Hz at rest — the strength of the jitter kill
BETA = 10.0         # cutoff gain per (palm-lengths/s) of speed — motion passes (2.6: was 2.0 = mushy)
D_CUTOFF = 2.5      # Hz — velocity-estimate filter (slow enough to not chase jitter)
SPIKE_FRAC = 0.25   # max single-frame jump in palm-lengths at rest (dt-scaled)
SPIKE_SPEED = 2.5   # extra budget = 2.5x current speed per frame — sustained
                    # motion self-authorizes; a teleport from rest stays tight
PALM_GLITCH = 0.40  # palm length change per frame above this = tracker glitch
SPEED_DEAD = 0.45   # palm-lengths/s of 'speed' that is just sensor noise: no cutoff boost below it


def _alpha(dt: float, cutoff_hz: float) -> float:
    tau = 1.0 / (2.0 * math.pi * cutoff_hz)
    return dt / (dt + tau)


class LandmarkStabilizer:
    """Adaptive smoothing + spike gate for the 21 landmarks of ONE hand.

    process(lms, now) -> [(x, y, z), ...] with the same shape as the input.
    Call reset() whenever the hand is lost or the tracked hand changes.
    """

    def __init__(self, min_cutoff: float = MIN_CUTOFF, beta: float = BETA,
                 d_cutoff: float = D_CUTOFF, spike_frac: float = SPIKE_FRAC,
                 enabled: bool = True) -> None:
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self.spike_frac = float(spike_frac)
        self.enabled = bool(enabled)
        self.reset()

    def reset(self) -> None:
        self._x = None      # filtered positions [21][3]
        self._v = None      # filtered velocities (units/s) [21][3]
        self._t = None
        self._rejects = 0   # diagnostics: frames rejected by the palm guard
        self._pending = None  # (palm, time) of the last scale-rejected frame
        self.gated = None     # last frame after the spike gate only (unsmoothed) — the cursor aim reads this
        self._g = None        # aim gate state: previous gated positions [21][3]
        self._gs = None       # aim gate state: gated speed per landmark (units/s)

    # ------------------------------------------------------------------ util
    @staticmethod
    def _palm(lms) -> float:
        ax, ay = float(lms[WRIST][0]), float(lms[WRIST][1])
        bx, by = float(lms[MIDDLE_MCP][0]), float(lms[MIDDLE_MCP][1])
        return max(1e-6, math.hypot(bx - ax, by - ay))

    # --------------------------------------------------------------- process
    def process(self, lms, now: float):
        if lms is None or len(lms) != N_LMS:
            return lms
        if not self.enabled:
            return lms
        if self._x is None or self._t is None or now <= self._t or now - self._t > 0.5:
            self._seed(lms, now)              # first frame / long gap / clock skew
            self.gated = [tuple(p) for p in lms]
            return list(lms)
        dt = min(0.25, now - self._t)
        self._t = now
        # palm-scale guard: a big palm-length jump is a tracker z-flip, not a hand
        palm_now = self._palm(lms)
        palm_prev = self._palm(self._x)
        if palm_now < 0.02 or palm_now > 0.9:
            self._rejects += 1
            return [tuple(p) for p in self._x]
        if abs(palm_now - palm_prev) > PALM_GLITCH * palm_prev:
            # z-flip (one frame) vs a real change of apparent size. A glitch is
            # gone next frame; a persistent change (hand leaned in/out, turned
            # toward the camera) survives — re-seed onto it instead of holding
            # the old frame forever (which froze the cursor permanently).
            pend = self._pending
            if pend is not None and abs(palm_now - pend[0]) <= PALM_GLITCH * pend[0]:
                self._pending = None
                self._seed(lms, now)
                self.gated = [tuple(p) for p in lms]
                return list(lms)
            self._pending = (palm_now, now)
            self._rejects += 1
            return [tuple(p) for p in self._x]
        self._pending = None
        a_d = _alpha(dt, self.d_cutoff)
        out = []
        gated = []
        for i in range(N_LMS):
            p = lms[i]
            fx, fy, fz = self._x[i]
            vx, vy, vz = self._v[i]
            x, y, z = float(p[0]), float(p[1]), float(p[2])
            rx, ry, rz = x, y, z              # raw, for the aim gate
            # speed from PREVIOUS frames only — a teleport must not authorize
            # its own budget within the same frame
            speed = math.hypot(vx, vy)
            budget = (self.spike_frac + SPIKE_SPEED * (speed / palm_prev) * dt) * palm_prev
            jx, jy = x - fx, y - fy
            jump = math.hypot(jx, jy)
            if jump > budget > 0:
                pull = budget / jump
                x = fx + jx * pull
                y = fy + jy * pull
                z = fz + (z - fz) * pull
            # --- aim gate: spike protection relative to the PREVIOUS GATED point, not to the
            # (lagging, heavily smoothed) filter state, so the cursor path stays unsmoothed
            gpx, gpy, gpz = self._g[i]
            gs = self._gs[i]
            bud_g = (self.spike_frac + SPIKE_SPEED * (gs / palm_prev) * dt) * palm_prev
            jgx, jgy = rx - gpx, ry - gpy
            jg = math.hypot(jgx, jgy)
            if jg > bud_g > 0:
                pg = bud_g / jg
                gnx, gny, gnz = gpx + jgx * pg, gpy + jgy * pg, gpz + (rz - gpz) * pg
            else:
                gnx, gny, gnz = rx, ry, rz
            self._gs[i] = 0.5 * gs + 0.5 * math.hypot(gnx - gpx, gny - gpy) / dt
            self._g[i] = (gnx, gny, gnz)
            gated.append((gnx, gny, gnz))
            # velocity filter tracks the GATED delta: sustained real motion
            # opens the budget over a few frames; a one-off teleport never does
            vx += a_d * ((x - fx) / dt - vx)
            vy += a_d * ((y - fy) / dt - vy)
            vz += a_d * ((z - fz) / dt - vz)
            # adaptive EMA: cutoff rises with speed -> no lag while moving
            cutoff = self.min_cutoff + self.beta * max(0.0, speed / palm_prev - SPEED_DEAD)
            a = _alpha(dt, cutoff)
            fx += a * (x - fx)
            fy += a * (y - fy)
            fz += a * (z - fz)
            self._x[i] = [fx, fy, fz]
            self._v[i] = [vx, vy, vz]
            out.append((fx, fy, fz))
        self.gated = gated
        return out

    def _seed(self, lms, now: float) -> None:
        self._x = [[float(p[0]), float(p[1]), float(p[2])] for p in lms]
        self._v = [[0.0, 0.0, 0.0] for _ in range(N_LMS)]
        self._g = [(float(p[0]), float(p[1]), float(p[2])) for p in lms]
        self._gs = [0.0] * N_LMS
        self._t = now


def _selftest() -> None:
    import random

    def hand(cx, cy, palm=0.2, seed=0):
        rnd = random.Random(seed)
        pts = []
        for i in range(N_LMS):
            a = i * 0.3
            r = palm * (0.4 + 0.6 * (i % 3) / 2.0)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a), 0.0))
        pts[WRIST] = (cx, cy, 0.0)
        pts[MIDDLE_MCP] = (cx + palm, cy, 0.0)
        return pts

    # 1) rest jitter is reduced
    st = LandmarkStabilizer()
    rnd = random.Random(7)
    raw, sm = [], []
    t = 0.0
    for _ in range(90):
        t += 1 / 30.0
        pts = [(x + rnd.uniform(-0.01, 0.01), y + rnd.uniform(-0.01, 0.01), z)
               for (x, y, z) in hand(0.5, 0.5)]
        out = st.process(pts, t)
        raw.append(pts[8][0])
        sm.append(out[8][0])
    var = lambda v: sum((x - sum(v) / len(v)) ** 2 for x in v) / len(v)
    assert var(sm) < 0.2 * var(raw), (var(raw), var(sm))
    # 2) teleport is clamped, recovery next frame
    st = LandmarkStabilizer()
    t = 0.0
    for _ in range(10):
        t += 1 / 30.0
        st.process(hand(0.5, 0.5), t)
    tele = hand(0.5, 0.5)
    tele[8] = (0.9, 0.9, 0.0)                     # fingertip teleports
    out = st.process(tele, t + 1 / 30.0)
    assert out[8][0] < 0.7, out[8]                # far from the teleport target
    assert st.gated[8][0] < 0.7, st.gated[8]      # the unsmoothed aim path is gated too
    out2 = st.process(hand(0.5, 0.5), t + 2 / 30.0)
    assert abs(out2[8][0] - 0.5) < 0.25, out2[8]  # recovers
    assert abs(st.gated[8][0] - hand(0.5, 0.5)[8][0]) < 0.03, st.gated[8]   # back on the real tip
    # 3) fast swipe is followed
    st = LandmarkStabilizer()
    t, x = 0.0, 0.3
    for _ in range(12):
        t += 1 / 30.0
        st.process(hand(x, 0.5), t)
    tip_off = hand(x, 0.5)[8][0] - x          # fingertip sits left of the palm x
    for _ in range(6):                        # 0.3 -> 0.9 in 0.2s
        x += 0.1
        t += 1 / 30.0
        out = st.process(hand(x, 0.5), t)
    lag = (x + tip_off) - out[8][0]
    assert lag < 0.2, (out[8][0], x, lag)     # under ~0.2 palm lag on a hard flick
    glag = (x + tip_off) - st.gated[8][0]
    assert glag < 0.1, (st.gated[8][0], x, glag)      # the aim path follows even closer
    # 4) palm-scale glitch frame is rejected
    st = LandmarkStabilizer()
    t = 0.0
    for _ in range(10):
        t += 1 / 30.0
        st.process(hand(0.5, 0.5), t)
    held_tip = st.process(hand(0.5, 0.5), t)[8][0]   # fingertip x before the glitch
    glitch = hand(0.5, 0.5, palm=0.6)                # palm 3x -> z-flip
    out = st.process(glitch, t + 1 / 30.0)
    assert abs(out[8][0] - held_tip) < 0.02, (out[8], held_tip)  # held the old frame
    print("lmsmooth self-tests passed")


if __name__ == "__main__":
    _selftest()
