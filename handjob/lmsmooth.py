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
"""

from __future__ import annotations

import math

N_LMS = 21
WRIST, MIDDLE_MCP = 0, 9

# 1€ filter defaults (tuned for 30-60 fps landmark streams; measured on
# synthetic jitter+swipe: rest jitter ~13% of raw variance, swipe lag ~0.1 palm)
MIN_CUTOFF = 0.5    # Hz at rest — the strength of the jitter kill
BETA = 2.0          # cutoff gain per (palm-lengths/s) of speed — motion passes
D_CUTOFF = 2.5      # Hz — velocity-estimate filter (slow enough to not chase jitter)
SPIKE_FRAC = 0.25   # max single-frame jump in palm-lengths at rest (dt-scaled)
SPIKE_SPEED = 2.5   # extra budget = 2.5x current speed per frame — sustained
                    # motion self-authorizes; a teleport from rest stays tight
PALM_GLITCH = 0.60  # palm length change vs the last ACCEPTED frame above this =
                    # tracker glitch (held one frame). See the ponytail note in
                    # process(): 40% fought real rotation; a depth inversion is 2-4x.


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
        self._held_last = False  # the previous frame was palm-guarded (hold once)
        self._palm_ref = 0.0  # palm length of the last ACCEPTED frame
        self._pending = None  # (palm, time) of the last scale-rejected frame

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
            return list(lms)
        dt = min(0.25, now - self._t)
        self._t = now
        # palm-scale guard: a big palm-length jump is a tracker glitch, not a hand.
        # The reference is the palm of the last ACCEPTED frame (not the filtered
        # landmarks, which lag and re-trigger the guard on the frame after every
        # hold). A glitch is held for ONE frame; anything that persists is real
        # motion — the hand rotated, leaned in, or the tracker re-locked at a new
        # depth — and must be followed, because holding it froze the cursor solid
        # while the hand kept moving.
        #
        # ponytail: PALM_GLITCH=0.60 is a deliberate ceiling. 40% was fighting
        # real rotation (a fast flick changes the projected wrist->MCP length by
        # ~cos of the yaw delta, so 50%+/frame is physically reachable) and
        # dropping half the frames. Raise it if a real z-flip ever slips through;
        # a genuine depth inversion changes length by 2-4x, well past this.
        palm_now = self._palm(lms)
        if palm_now < 0.02 or palm_now > 0.9:
            self._rejects += 1
            return [tuple(p) for p in self._x]
        if not self._held_last and abs(palm_now - self._palm_ref) > PALM_GLITCH * self._palm_ref:
            self._held_last = True
            self._rejects += 1
            return [tuple(p) for p in self._x]
        self._held_last = False
        self._palm_ref = palm_now
        a_d = _alpha(dt, self.d_cutoff)
        out = []
        for i in range(N_LMS):
            p = lms[i]
            fx, fy, fz = self._x[i]
            vx, vy, vz = self._v[i]
            x, y, z = float(p[0]), float(p[1]), float(p[2])
            # speed from PREVIOUS frames only — a teleport must not authorize
            # its own budget within the same frame
            speed = math.hypot(vx, vy)
            budget = (self.spike_frac + SPIKE_SPEED * (speed / palm_now) * dt) * palm_now
            jx, jy = x - fx, y - fy
            jump = math.hypot(jx, jy)
            if jump > budget > 0:
                pull = budget / jump
                x = fx + jx * pull
                y = fy + jy * pull
                z = fz + (z - fz) * pull
            # velocity filter tracks the GATED delta: sustained real motion
            # opens the budget over a few frames; a one-off teleport never does
            vx += a_d * ((x - fx) / dt - vx)
            vy += a_d * ((y - fy) / dt - vy)
            vz += a_d * ((z - fz) / dt - vz)
            # adaptive EMA: cutoff rises with speed -> no lag while moving
            cutoff = self.min_cutoff + self.beta * (speed / palm_now)
            a = _alpha(dt, cutoff)
            fx += a * (x - fx)
            fy += a * (y - fy)
            fz += a * (z - fz)
            self._x[i] = [fx, fy, fz]
            self._v[i] = [vx, vy, vz]
            out.append((fx, fy, fz))
        return out

    def _seed(self, lms, now: float) -> None:
        self._x = [[float(p[0]), float(p[1]), float(p[2])] for p in lms]
        self._v = [[0.0, 0.0, 0.0] for _ in range(N_LMS)]
        self._held_last = False
        self._palm_ref = self._palm(lms)
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
    out2 = st.process(hand(0.5, 0.5), t + 2 / 30.0)
    assert abs(out2[8][0] - 0.5) < 0.25, out2[8]  # recovers
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
