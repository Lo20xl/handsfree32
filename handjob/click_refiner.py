"""click_refiner.py - crisp pinch clicks from 30 Hz hand tracking (pure logic, no UI deps).

Drop-in for gestures.ClickGesture:  update_left / update_right return the same
events ("left_down", "left_up", "right_click"), `.pinch.threshold`, `.left_down`,
`.right_held`, `.reset()` exist.  New: observe(), cursor_target(), release_all(),
`.anchor`, `.state`.

What changes vs. the 90 ms-sustain / 1.55x-release / fixed 25 px lock version:

  press   enter after 2 frames below threshold, OR on the FIRST frame when two
          successive frames show a decisive closing velocity (tie-break), OR one
          frame early when the extrapolated ratio (predict_s ahead) will be inside
          (opt-in: predict_s>0 fires one frame early)
          -> ~60-100 ms sooner at 30 Hz.  A single-frame glitch never clicks
          (fast path needs two consecutive closing steps coming from "fingers apart").
  release hysteresis 1.25x (was 1.55x); leaves after 2 frames, or at once when two
          successive frames show a fast opening.  A one-frame tracker/disambiguation
          blip no longer drops a drag.
  freeze  the cursor freezes at the AIM position the moment a closing pinch is
          recognised (pre-press), so the hand wobble of closing the fingers can never
          smear the click.  Aim position = where the hand was when the fingers began
          to close (not a fixed 0.12 s lookback), averaged over a few frames.
  drag    unlock radius is adaptive: bigger for a shaky hand, shrinks with hold time
          (taps / double-clicks stay put, a held pinch turns into a drag after a few
          px), and a fast hand breaks the lock at once.  On unlock the cursor eases
          from the anchor into the hand (no jump).
  double  a press within `dbl_time` of the previous one and within `dbl_px` snaps to
  click   the previous anchor so Windows registers a double-click.
"""
from __future__ import annotations

import math
from collections import deque
from typing import List, Optional, Tuple

__all__ = ["ClickRefiner"]

_EPS = 0.012


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


class _Pinch:
    """One thumb-finger pair. ratio = dist(thumb_tip, finger_tip) / palm_scale."""

    def __init__(self, owner: "ClickRefiner", threshold: float) -> None:
        self.o = owner
        self.threshold = threshold
        self.reset()

    def reset(self) -> None:
        self.held = False
        self.armed = False          # closing pinch recognised, button not yet down
        self.arm_t0 = 0.0
        self.run_start: Optional[float] = None   # when the current closing run began
        self.below = 0
        self.above = 0
        self.rdot = 0.0             # ratio velocity (1/s), lightly smoothed
        self._r1: Optional[float] = None
        self._r2: Optional[float] = None
        self._t1: Optional[float] = None

    def update(self, r: float, now: float) -> Optional[str]:
        o, thr = self.o, self.threshold
        if self._t1 is None or now - self._t1 > 0.25 or now <= self._t1:
            self._r1 = self._r2 = None
            self.rdot = 0.0
        else:
            self.rdot = 0.65 * (r - self._r1) / (now - self._t1) + 0.35 * self.rdot
        r1, r2 = self._r1, self._r2
        closing2 = r1 is not None and r2 is not None and r2 > r1 + _EPS and r1 > r + _EPS
        opening2 = r1 is not None and r2 is not None and r2 < r1 - _EPS and r1 < r - _EPS

        if r1 is not None and r < r1 - _EPS:               # start of the closing motion = aim moment
            if self.run_start is None:
                self.run_start = self._t1
        elif r1 is not None and r > r1 + 0.03:
            self.run_start = None

        ev = None
        if not self.held:
            hit = r < thr
            fast = closing2 and self.rdot < -o.fast_closing and r1 < 2.2 * thr   # velocity tie-break
            early = (o.predict_s > 0.0 and not hit and closing2 and r < 1.3 * thr
                     and self.rdot < -o.fast_closing and r + self.rdot * o.predict_s < 0.85 * thr)
            if hit or early:
                self.below += 1
                if self.below >= o.confirm_frames or fast or early:
                    self.held, ev = True, "enter"
                    self.below = self.above = 0
                    self.armed = False
            else:
                self.below = 0
            if not self.held:                               # pre-freeze arming
                if (r < o.arm_level * thr and closing2 and self.rdot < -o.arm_rate
                        and o._speed < o.arm_max_speed * o.S):          # deliberate closing, hand not flying
                    if not self.armed:
                        self.armed, self.arm_t0 = True, now
                elif self.armed and (r > 1.15 * o.arm_level * thr or now - self.arm_t0 > o.arm_timeout
                                     or (self.rdot > 1.0 and r > 1.2 * thr)):
                    self.armed = False
        else:
            if r > o.release_ratio * thr:
                self.above += 1
                if self.above >= 2 or (opening2 and self.rdot > o.fast_opening):
                    self.held, ev = False, "leave"
                    self.above = self.below = 0
                    self.run_start = None
            else:
                self.above = 0
        self._r2, self._r1, self._t1 = self._r1, r, now
        return ev


class ClickRefiner:
    """Pinch -> click events + cursor freeze/drag target.  Call order per frame:

        refiner.observe(now, x, y)                 # tracked cursor target, screen px
        events  = refiner.update_left(l_ratio, now) + refiner.update_right(r_ratio, now)
        # (not pointing: events = refiner.release_all(now))
        tx, ty  = refiner.cursor_target(now)       # feed THIS to the motion engine
        # on "left_down"/"right_click": cursor must be at refiner.anchor before the click
    """

    def __init__(self, threshold: float, *, release_ratio: float = 1.25, confirm_frames: int = 2,
                 fast_closing: float = 2.5, fast_opening: float = 2.5, predict_s: float = 0.0,
                 arm_level: float = 1.5, arm_rate: float = 3.0, arm_timeout: float = 0.3,
                 arm_max_speed: float = 350.0,
                 lookback_max: float = 0.25, lookback_min: float = 0.03,
                 right_cooldown: float = 0.25, drag_px: float = 12.0, drag_px_max: float = 40.0,
                 v_break: float = 500.0, dbl_time: float = 0.5, dbl_px: float = 10.0,
                 px_scale: float = 1.0) -> None:
        self.release_ratio, self.confirm_frames = release_ratio, confirm_frames
        self.fast_closing, self.fast_opening, self.predict_s = fast_closing, fast_opening, predict_s
        self.arm_level, self.arm_rate, self.arm_timeout = arm_level, arm_rate, arm_timeout
        self.arm_max_speed = arm_max_speed
        self.lookback_max, self.lookback_min = lookback_max, lookback_min
        self.right_cooldown, self.drag_px, self.drag_px_max = right_cooldown, drag_px, drag_px_max
        self.v_break, self.dbl_time, self.dbl_px, self.S = v_break, dbl_time, dbl_px, max(0.05, px_scale)
        self.pinch = _Pinch(self, threshold)        # `.pinch.threshold` like ClickGesture (left detector)
        self._R = _Pinch(self, threshold)
        self.anchor: Optional[Tuple[float, float]] = None
        self.reset()

    # ----------------------------------------------------------- compat surface
    @property
    def left_down(self) -> bool:
        return self.pinch.held

    @property
    def right_held(self) -> bool:
        return self._R.held

    @property
    def state(self) -> str:
        return "drag" if self._drag else "frozen" if self._lock is not None else "free"

    def reset(self) -> None:
        self.pinch.reset()
        self._R.reset()
        self._hist: deque = deque(maxlen=48)
        self._live: Tuple[float, float] = (0.0, 0.0)
        self._speed = 0.0
        self._jit = 2.0                 # px/frame hand micro-jitter while (nearly) still
        self._lock: Optional[Tuple[float, float]] = None
        self._drag = False
        self._blend: Optional[Tuple[float, float, float, float, float]] = None
        self._t_press = 0.0
        self._last_right = -1e9
        self._prev: Optional[Tuple[float, float, float]] = None   # last anchor + time (double-click)

    # ---------------------------------------------------------------- per frame
    def observe(self, now: float, x: float, y: float) -> None:
        if self._hist:
            t0, x0, y0 = self._hist[-1]
            dt = now - t0
            if dt > 1e-4:
                d = math.hypot(x - x0, y - y0)
                inst = d / dt
                self._speed = 0.5 * self._speed + 0.5 * inst
                if self._lock is None and inst < 150.0 * self.S:
                    self._jit += 0.08 * (d - self._jit)
        self._hist.append((now, x, y))
        self._live = (x, y)

    def reseed(self, now: float, x: float, y: float) -> None:
        """The mapping jumped on purpose (re-anchor on point-engage): the
        position history before `now` describes the OLD mapping, so a click
        anchor computed from it would snap the cursor back to a stale spot.
        Keep only the current position; pinch state (held buttons) survives."""
        self._hist.clear()
        self._hist.append((now, x, y))
        self._live = (x, y)
        self._speed = 0.0

    def update_left(self, ratio: float, now: float) -> List[str]:
        ev = self.pinch.update(ratio, now)
        self._maybe_start_lock(now)
        if ev == "enter":
            self._on_press(now)
            return ["left_down"]
        if ev == "leave":
            self._on_release(now)
            return ["left_up"]
        return []

    def update_right(self, ratio: float, now: float) -> List[str]:
        self._R.threshold = self.pinch.threshold
        ev = self._R.update(ratio, now)
        self._maybe_start_lock(now)
        if ev == "enter":
            self._on_press(now)
            if not self.pinch.held and now - self._last_right >= self.right_cooldown:
                self._last_right = now
                return ["right_click"]
        elif ev == "leave":
            self._on_release(now)
        return []

    def release_all(self, now: float) -> List[str]:
        """Not pointing (scroll/idle/hand lost): drop everything immediately."""
        events = ["left_up"] if self.pinch.held else []
        self.pinch.reset()
        self._R.reset()
        if events or self._lock is not None:
            self._on_release(now)
        return events

    def cursor_target(self, now: float) -> Tuple[float, float]:
        lx, ly = self._live
        engaged = self.pinch.held or self._R.held
        arming = self.pinch.armed or self._R.armed
        if not (engaged or arming):
            if self._lock is not None:
                self._end_lock(now, 0.0, 0.08)
        elif self._lock is None:
            self._start_lock(now)

        if self._lock is not None and not self._drag:
            ax, ay = self._lock
            r0 = self._r0()
            d = math.hypot(lx - ax, ly - ay)
            if engaged:
                r = self._radius(now - self._t_press, r0)
                if d > r or (self._speed > self.v_break * self.S and d > 0.45 * r0):
                    self._drag = True
                    self._blend = (ax, ay, now, 0.4, 0.10)       # ease from anchor into the hand
            elif d > 1.5 * r0:                                    # hand walked away while arming: abort
                self.pinch.armed = self._R.armed = False
                self._end_lock(now, 0.3, 0.10)
            else:
                return ax, ay
        # NOTE: a release blend must NOT be cancelled here just because a new
        # press started — `_start_lock` already clears it, and this same field
        # carries the drag-UNLOCK ease, which has to survive while the button is
        # held. Cancelling on `engaged` made the unlock jump straight to the live
        # hand position (caught by the self-test: "target jumped on unlock").
        if self._blend is not None:
            ax, ay, t0, s0, dur = self._blend
            s = s0 + (1.0 - s0) * min(1.0, (now - t0) / dur)
            if s >= 1.0:
                self._blend = None
            else:
                return ax + (lx - ax) * s, ay + (ly - ay) * s
        if self._lock is not None and not self._drag:
            return self._lock
        return lx, ly

    # ---------------------------------------------------------------- internals
    def _r0(self) -> float:
        S = self.S
        return _clamp((self.drag_px + 3.0 * self._jit / S) * S, 0.9 * self.drag_px * S, self.drag_px_max * S)

    def _radius(self, hold: float, r0: float) -> float:
        """Unlock radius: r0 for the first 150 ms of a press, easing to 0.45*r0 by 450 ms."""
        r_min = max(5.0 * self.S, 0.45 * r0)
        if hold <= 0.15:
            return r0
        if hold >= 0.45:
            return r_min
        return r0 + (r_min - r0) * (hold - 0.15) / 0.30

    def _pos_at(self, t: float) -> Tuple[float, float]:
        sx = sy = 0.0
        n = 0
        near = None
        for ts, x, y in self._hist:
            if near is None or abs(ts - t) < abs(near[0] - t):
                near = (ts, x, y)
            if t - 0.05 <= ts <= t + 0.02:
                sx += x
                sy += y
                n += 1
        if n:
            return sx / n, sy / n
        return (near[1], near[2]) if near else self._live

    def _maybe_start_lock(self, now: float) -> None:
        if self._lock is None and (self.pinch.held or self.pinch.armed or self._R.held or self._R.armed):
            self._start_lock(now)

    def _start_lock(self, now: float) -> None:
        det = self.pinch if (self.pinch.held or self.pinch.armed) else self._R
        t_a = det.run_start if det.run_start is not None else now - 0.12
        t_a = _clamp(t_a, now - self.lookback_max, now - self.lookback_min)
        x, y = self._pos_at(t_a)
        pv = self._prev
        if pv is not None and now - pv[2] <= self.dbl_time and math.hypot(x - pv[0], y - pv[1]) <= self.dbl_px * self.S:
            x, y = pv[0], pv[1]                                   # double-click magnet
        self._lock = (x, y)
        self._drag = False
        self._blend = None

    def _end_lock(self, now: float, s0: float, dur: float) -> None:
        if self._lock is not None and not self._drag:
            ax, ay = self._lock
            self._blend = (ax, ay, now, s0, dur)
        self._lock = None
        self._drag = False

    def _on_press(self, now: float) -> None:
        self._maybe_start_lock(now)
        self._t_press = now
        self.anchor = self._lock
        if self._lock is not None:
            self._prev = (self._lock[0], self._lock[1], now)

    def _on_release(self, now: float) -> None:
        if self._lock is not None:
            self._prev = (self._lock[0], self._lock[1], now)
        if not (self.pinch.held or self._R.held or self.pinch.armed or self._R.armed):
            self._end_lock(now, 0.0, 0.08)


# =============================================================================
# self-test:  python click_refiner.py
# =============================================================================
def _selftest() -> None:
    DT, THR = 1.0 / 30.0, 0.35

    class Legacy:                                     # gestures.Pinch (sustain 90 ms, release 1.55x)
        def __init__(self, thr, sustain=0.09):
            self.thr, self.sustain, self.held, self.since = thr, sustain, False, 0.0

        def update(self, r, now):
            if not self.held:
                if r < self.thr:
                    self.since = self.since or now
                    if now - self.since >= self.sustain:
                        self.held = True
                        return "enter"
                else:
                    self.since = 0.0
            elif r > self.thr * 1.55:
                self.held, self.since = False, 0.0
                return "leave"
            return None

    def run(seq, t0=1.0, pos=None, refiner=None):
        """Feed a ratio sequence at 30 Hz. Returns (refiner, [(frame, event)])."""
        rf = refiner or ClickRefiner(THR)
        out = []
        for i, r in enumerate(seq):
            now = t0 + i * DT
            x, y = pos(now) if pos else (500.0, 300.0)
            rf.observe(now, x, y)
            for e in rf.update_left(r, now) + rf.update_right(1.0, now):
                out.append((i, e))
            rf.cursor_target(now)
        return rf, out

    # a human tap: open -> touch in ~100 ms -> hold ~100 ms -> open in ~100 ms
    tap = [1.0] * 8 + [0.85, 0.60, 0.30, 0.14, 0.11, 0.11, 0.12, 0.20, 0.45, 0.80, 1.0, 1.0, 1.0]
    rf, ev = run(tap)
    assert [e for _, e in ev] == ["left_down", "left_up"], ev
    down_i, up_i = ev[0][0], ev[1][0]
    lg, lg_ev = Legacy(THR), []
    for i, r in enumerate(tap):
        e = lg.update(r, 1.0 + i * DT)
        if e:
            lg_ev.append((i, e))
    gain_down = (lg_ev[0][0] - down_i) * DT * 1000
    gain_up = (lg_ev[1][0] - up_i) * DT * 1000
    assert gain_down >= 60.0 and gain_up >= 0.0, (gain_down, gain_up)
    print(f"tap     : press fires {gain_down:.0f} ms sooner, release {gain_up:.0f} ms sooner than the 90 ms-sustain logic")

    # glitches never click / never drop a drag
    _, ev = run([1.0] * 6 + [0.10] + [1.0] * 6)
    assert ev == [], ev
    held = [1.0] * 6 + [0.7, 0.4, 0.2, 0.15] + [0.15] * 4 + [1.0] + [0.15] * 4 + [0.8, 0.9, 1.0, 1.0, 1.0]
    _, ev = run(held)
    assert [e for _, e in ev] == ["left_down", "left_up"], ev
    assert ev[1][0] >= 6 + 4 + 4 + 1 + 4, "one-frame blip released the button"
    print("glitch  : 1-frame dip never clicks, 1-frame blip never releases a held button")

    # anchor = aim position when the fingers started closing, not the pinch wobble
    def hand(now):                                    # rests on (800,400), fingers start closing, hand wobbles away
        t_close = 1.0 + 8 * DT
        if now < t_close:
            return 800.0 - 300.0 * max(0.0, t_close - 2 * DT - now), 400.0   # hand brakes to rest 2 frames earlier
        return 800.0 + 120.0 * (now - t_close), 400.0 + 60.0 * (now - t_close)
    rf, ev = run(tap, pos=hand)
    ax, ay = rf.anchor
    assert math.hypot(ax - 800.0, ay - 400.0) < 4.0, (ax, ay)
    print(f"anchor  : click lands {math.hypot(ax - 800.0, ay - 400.0):.1f}px from the aim point despite closing wobble")

    # pre-freeze: cursor target is pinned while the fingers are still closing
    rf = ClickRefiner(THR)
    targets = []
    for i, r in enumerate([1.0] * 8 + [0.85, 0.60, 0.42, 0.30, 0.14, 0.11, 0.11]):
        now = 1.0 + i * DT
        x = 800.0 + (0.0 if i < 8 else 1.5 * (i - 8))          # hand drifts 1.5 px/frame once the pinch starts
        rf.observe(now, x, 400.0)
        rf.update_left(r, now)
        rf.update_right(1.0, now)
        targets.append(rf.cursor_target(now)[0])
    assert max(targets[10:]) - min(targets[10:]) < 1.0 and rf.state == "frozen", targets
    print("freeze  : cursor target pinned during the closing motion (before the button goes down)")

    # drag: frozen under radius, fast hand breaks lock, held pinch shrinks the radius, no jump on unlock
    def drag_run(move_after, dx_per_frame, hold_before_move):
        rf = ClickRefiner(THR)
        x, res = 800.0, []
        seq = [1.0] * 8 + [0.6, 0.3, 0.12] + [0.12] * 40
        t_press = None
        for i, r in enumerate(seq):
            now = 1.0 + i * DT
            if t_press is not None and now - t_press >= hold_before_move:
                x += dx_per_frame
            rf.observe(now, x, 400.0)
            e = rf.update_left(r, now) + rf.update_right(1.0, now)
            if "left_down" in e:
                t_press = now
            tx, _ = rf.cursor_target(now)
            res.append((now, x, tx, rf.state))
        return rf, res, t_press

    _, res, _ = drag_run(None, 1.0, 0.0)                      # 1 px/frame right after press: tap-like wobble
    assert all(s == "frozen" for *_, s in res[10:16]), "tiny early movement must stay frozen"
    _, res, _ = drag_run(None, 14.0, 0.0)                     # 14 px/frame (~420 px/s) right after press
    assert any(s == "drag" for *_, s in res), "fast hand must break the lock"
    j = next(i for i, r_ in enumerate(res) if r_[3] == "drag")
    assert abs(res[j][2] - res[j - 1][2]) < 0.6 * 14.0 * 3, "target jumped on unlock"
    last = res[-1]
    assert abs(last[2] - last[1]) < 1e-6, "drag target must converge on the hand"
    _, res, _ = drag_run(None, 2.0, 0.55)                     # held 0.55 s, then slow 2 px/frame (60 px/s)
    assert any(s == "drag" for *_, s in res), "held pinch must turn into a drag after a few px"
    _, res, tp = drag_run(None, 2.0, 0.0)                  # same slow move right after press stays a click ...
    assert not any(s == "drag" and t < tp + 0.15 for t, _, _, s in res), "slow early movement should stay frozen"
    assert any(s == "drag" for *_, s in res), "... but a pinch held while moving becomes a drag"
    print("drag    : radius adapts (early=sticky, held=sensitive), fast hand breaks lock, eased unlock")

    # right click: once per pinch, cooldown, re-arms after release
    rf = ClickRefiner(THR)
    seq = [1.0] * 6 + [0.7, 0.4, 0.2, 0.12] + [0.12] * 10 + [0.6, 0.9, 1.0, 1.0, 1.0] + [0.7, 0.4, 0.2, 0.12, 0.12, 0.8, 1.0]
    clicks = []
    for i, r in enumerate(seq):
        now = 1.0 + i * DT
        rf.observe(now, 600.0, 300.0)
        rf.update_left(1.0, now)
        clicks += [i for e in rf.update_right(r, now) if e == "right_click"]
    assert len(clicks) == 2 and rf.left_down is False, clicks
    print("right   : exactly one click per pinch, held pinch does not repeat, second pinch fires")

    # double-click magnet
    rf = ClickRefiner(THR)
    pos = lambda now: (700.0 + (6.0 if now > 1.0 + 25 * DT else 0.0), 300.0)
    anchors = []
    seq = [1.0] * 6 + [0.5, 0.2, 0.12, 0.12, 0.6, 1.0, 0.5, 0.2, 0.12, 0.12, 0.8, 1.0, 1.0]
    for i, r in enumerate(seq):
        now = 1.0 + i * DT
        x, y = pos(now) if i > 14 else (700.0, 300.0)
        rf.observe(now, x, y)
        if "left_down" in rf.update_left(r, now) + rf.update_right(1.0, now):
            anchors.append(rf.anchor)
        rf.cursor_target(now)
    assert len(anchors) == 2 and anchors[0] == anchors[1], anchors
    print("dbl     : second press snapped onto the first anchor")

    # release_all frees the button immediately
    rf, ev = run([1.0] * 6 + [0.5, 0.2, 0.12, 0.12])
    assert rf.left_down and rf.release_all(5.0) == ["left_up"] and not rf.left_down
    print("all click-refiner self-tests passed")


if __name__ == "__main__":
    _selftest()
