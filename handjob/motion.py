"""motion.py - high-rate cursor motion engine for camera-driven pointing.

The camera delivers 10-30 position samples/s with jittery timing. A real mouse
delivers hundreds. CursorMotion bridges the gap:

    engine thread (camera rate)            emitter thread (max_rate Hz)
    ---------------------------            ----------------------------
    ingest(t, x, y)  ------------------>   dead-reckon between samples
                                           -> low-pass follower
                                           -> anti-overshoot clamp
                                           -> fn(x, y)  (only on whole-pixel change)

Pipeline per sample (all pure-float math, no allocations on the hot path):
  1. speed-adaptive 1-euro smoothing of the raw sample  (steady at rest, crisp in motion)
  2. velocity from the last few smoothed samples, deliberately CONSERVATIVE:
     a deceleration is trusted immediately, an acceleration only half-way
  3. deceleration estimate -> constant-decel kinematics with a stop point, so the
     predicted path can never run past where the hand would physically stop

Pipeline per emitter tick:
  4. target = smoothed sample + velocity * (time since sample)       (interpolation)
              + velocity * prediction_ms                             (lead, speed gated)
  5. if the next sample is overdue the prediction retracts and the target slides
     onto the LAST RAW sample (stop detection -> exact settle)
  6. first-order follower (cutoff grows with speed) chases the target
  7. hard guard: output may never be further along the travel direction than the
     target's own lead (so it cannot overshoot the last sample after a stop)

`t` in ingest() may come from ANY monotonic clock (perf_counter, monotonic,
time.time()). Only differences are used; the offset to the emitter clock is
tracked with a min-filter so delivery latency/jitter never leaks in.
"""
from __future__ import annotations

import math
import sys
import threading
import time
from collections import deque
from typing import Callable, Optional, Tuple

__all__ = ["CursorMotion"]

_TWO_PI = 2.0 * math.pi


def _smoothstep(e0: float, e1: float, x: float) -> float:
    if x <= e0:
        return 0.0
    if x >= e1:
        return 1.0
    u = (x - e0) / (e1 - e0)
    return u * u * (3.0 - 2.0 * u)


def _lp(cutoff_hz: float, dt: float) -> float:
    """Exact first-order low-pass coefficient for a (possibly uneven) step dt."""
    return 1.0 - math.exp(-_TWO_PI * cutoff_hz * dt)


def _extrap(v: float, a: float, tau: float) -> float:
    """Distance travelled in `tau` s at speed v with (<=0) deceleration a.
    With deceleration the path stops at v^2/(2|a|) and never goes beyond."""
    if tau <= 0.0:
        return 0.0
    if a < -1.0:
        ts = v / -a
        if tau > ts:
            tau = ts
        return v * tau + 0.5 * a * tau * tau
    return v * tau


class CursorMotion:
    """Turns jittery 10-30 Hz samples into a smooth 120-200 Hz cursor stream.

    prediction_ms : how far ahead of the newest sample the cursor aims while the
                    hand moves (hides camera + inference latency). 0 disables.
    smoothness    : 0..1. Rest-jitter suppression. 0 = crisp, 1 = very steady.
                    Speed-adaptive: fast motion is barely filtered at any value.
    max_rate      : emitter rate in Hz (clamped 30..500).
    speed_scale   : multiplies every px/s threshold (use screen_width / 1920).
    clock         : time source for the emitter (tests inject a fake one).
    """

    REACQUIRE_GAP = 0.35      # s without samples -> next sample teleports the cursor
    RING_SPAN = 0.20          # s of smoothed samples kept for velocity estimation
    D_CUT = 2.0               # Hz, speed-estimate low-pass inside the 1-euro stage
    V_DEAD = 60.0             # px/s of 'speed' treated as sensor noise (no cutoff boost)
    ACC_EMA = 0.7             # smoothing of the braking estimate
    ACC_GAIN = 2.0            # assume braking continues harder than measured (anti-overshoot)
    LEAD_CAP_PX = 40.0        # soft ceiling on the lead distance (px at speed_scale=1)

    def __init__(self, prediction_ms: float = 45.0, smoothness: float = 0.5,
                 max_rate: float = 144.0, speed_scale: float = 1.0,
                 clock: Callable[[], float] = time.perf_counter,
                 hold_px: float = 0.0) -> None:
        self._clock = clock
        self._lock = threading.Lock()        # guards all motion state
        self._emit_lock = threading.Lock()   # serialises emission (emitter vs snap)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fn: Optional[Callable[[float, float], None]] = None
        self._timer_raised = False

        self._S = max(0.05, float(speed_scale))
        self._lead_cap = self.LEAD_CAP_PX
        self._hold = 0.0
        self._bx = self._by = 0.0            # hold-stage output (what is actually emitted)
        self._b_ok = False
        self.configure(prediction_ms, smoothness, max_rate, hold_px)

        # --- sample state (local-clock times) ---
        self._ring: deque = deque(maxlen=5)  # (t, fx, fy) smoothed samples
        self._reset_samples()

        # --- output state ---
        self._ox = self._oy = 0.0
        self._have_out = False
        self._soft = False                   # True right after snap()/halt(): glide, don't teleport
        self._halted = False
        self._t_o = 0.0
        self._last_px = None                 # last emitted whole-pixel pair
        self._pos: Optional[Tuple[float, float]] = None  # last emitted (x, y)
        self._ticks = self._late = 0
        self._gap_max = 0.0

    # ------------------------------------------------------------------ config
    def configure(self, prediction_ms: Optional[float] = None,
                  smoothness: Optional[float] = None,
                  max_rate: Optional[float] = None,
                  hold_px: Optional[float] = None) -> None:
        """Live-tunable (safe to call from the UI thread).

        hold_px : rest-hold radius (px at speed_scale=1). While the hand is slow, the
                  emitted cursor only moves once the follower has drifted more than this
                  from it, and then trails it at exactly this distance (a backlash /
                  hysteresis stage). Sub-noise wobble never reaches the screen; the
                  radius collapses to 0 as speed rises, so deliberate motion has no lag.
                  0 disables (legacy behaviour)."""
        with self._lock:
            if hold_px is not None:
                self._hold = max(0.0, min(20.0, float(hold_px)))
            if prediction_ms is not None:
                self._lead = max(0.0, min(0.20, prediction_ms / 1000.0))
            if smoothness is not None:
                s = min(1.0, max(0.0, float(smoothness)))
                self._fc_min = 8.0 * (0.1 ** (1.15 * s))      # 8 Hz -> ~0.6 Hz at rest
                self._beta = 0.10 - 0.04 * s                  # cutoff gain per px/s
                self._ff_min = 24.0 - 10.0 * s                # follower cutoff at rest (Hz)
            if max_rate is not None:
                self._rate = min(500.0, max(30.0, float(max_rate)))

    def set_output(self, fn: Callable[[float, float], None]) -> None:
        """fn(x, y) emits one absolute move. Called from the emitter thread only."""
        self._fn = fn

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._enable_hires_timer()
        self._thread = threading.Thread(target=self._run, name="CursorMotion", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        th = self._thread
        if th is not None and th is not threading.current_thread():
            th.join(timeout=1.0)
        self._thread = None
        self._disable_hires_timer()

    def __enter__(self) -> "CursorMotion":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    @property
    def position(self) -> Optional[Tuple[float, float]]:
        """Last EMITTED position (what the OS cursor shows). Safe from any thread."""
        return self._pos

    def stats(self, reset: bool = True) -> dict:
        """Emitter health: ticks, late ticks (gap > 2 periods) and worst gap in ms.
        Late ticks while the engine runs inference = something holds the GIL."""
        out = {"ticks": self._ticks, "late": self._late, "max_gap_ms": round(self._gap_max * 1000.0, 1)}
        if reset:
            self._ticks = self._late = 0
            self._gap_max = 0.0
        return out

    # --------------------------------------------------------------------- API
    def ingest(self, t: float, x: float, y: float) -> None:
        """Feed one camera sample. `t` = capture timestamp (any monotonic clock, s)."""
        local = self._clock()
        with self._lock:
            self._halted = False
            self._ingest_locked(t, x, y, local)
            self._wake.set()

    def snap(self, x: float, y: float) -> None:
        """Teleport + emit NOW with zero velocity (use right before a click so the
        press lands exactly on the anchor). Ordered against the emitter."""
        now = self._clock()
        with self._emit_lock:
            with self._lock:
                self._reset_samples()
                self._rx = self._fx = self._ox = float(x)
                self._ry = self._fy = self._oy = float(y)
                self._t_s = now
                self._t_o = now
                self._have_out = True
                self._soft = True
                self._halted = False
                self._bx, self._by, self._b_ok = float(x), float(y), True
                self._wake.set()
            self._emit(float(x), float(y))

    def halt(self) -> None:
        """Input ended ON PURPOSE (pose left 'point', hand lost, disarmed): freeze the
        cursor exactly where it is - no prediction run-on, no retract. The next
        ingest() glides from here (or teleports if the gap is long)."""
        now = self._clock()
        with self._lock:
            if not self._have_out or self._halted:
                return
            self._halted = True
            x, y = self._bx if self._b_ok else self._ox, self._by if self._b_ok else self._oy
            self._ox, self._oy = x, y
            self._reset_samples()
            self._rx = self._fx = x
            self._ry = self._fy = y
            self._t_s = now
            self._t_o = now
            self._soft = True
            self._wake.set()

    # --------------------------------------------------------------- internals
    def _reset_samples(self) -> None:
        self._ring.clear()
        self._t_s: Optional[float] = None    # local time of newest sample
        self._t_prev: Optional[float] = None  # caller-domain time of newest sample
        self._rx = self._ry = 0.0            # newest raw sample
        self._fx = self._fy = 0.0            # newest smoothed sample
        self._dx = self._dy = 0.0            # 1-euro derivative state
        self._vx = self._vy = 0.0            # conservative velocity (px/s)
        self._speed = 0.0
        self._acc = 0.0                      # smoothed speed derivative (px/s^2)
        self._ux = self._uy = 0.0            # unit direction of v
        self._cux, self._cuy = 1.0, 0.0      # last significant direction (guard)
        self._gi = self._gl = 0.0            # interpolation / lead gates
        self._dt_ema = 1.0 / 30.0
        self._off = None                     # local - caller clock offset (min-filtered)

    def _ingest_locked(self, t: float, x: float, y: float, local: float) -> None:
        S = self._S
        # clock offset: min-filter so delivery jitter looks like "old sample", never "negative gap"
        cand = local - t
        if self._off is None or cand < self._off:
            self._off = cand
        else:
            self._off += (cand - self._off) * 0.002
        t_loc = t + self._off

        if self._t_prev is None or t - self._t_prev > self.REACQUIRE_GAP:
            # first sample / re-acquisition: no history to trust -> teleport
            keep_off = self._off
            self._reset_samples()
            self._off = keep_off
            self._rx = self._fx = x
            self._ry = self._fy = y
            if not (self._soft and self._have_out):
                self._ox, self._oy = x, y
            self._soft = False
            self._t_prev, self._t_s = t, t_loc
            self._t_o = local
            self._have_out = True
            self._ring.append((t_loc, x, y))
            return
        dt = t - self._t_prev
        if dt <= 1e-4:
            return                                    # duplicate / out-of-order frame
        if t_loc < self._t_s:
            t_loc = self._t_s
        self._t_prev, self._t_s = t, t_loc
        self._dt_ema += 0.25 * (min(0.25, max(0.005, dt)) - self._dt_ema)

        # 1) speed-adaptive 1-euro smoothing of the raw sample (2D, magnitude-driven cutoff)
        ad = _lp(self.D_CUT, dt)
        self._dx += ad * ((x - self._rx) / dt - self._dx)
        self._dy += ad * ((y - self._ry) / dt - self._dy)
        ex = math.hypot(self._dx, self._dy) / S - self.V_DEAD     # noise-floor dead band
        fc = self._fc_min + (self._beta * ex if ex > 0.0 else 0.0)
        a = _lp(fc, dt)
        self._fx += a * (x - self._fx)
        self._fy += a * (y - self._fy)
        self._rx, self._ry = x, y

        # 2) conservative velocity from smoothed samples
        ring = self._ring
        ring.append((t_loc, self._fx, self._fy))
        while len(ring) > 2 and t_loc - ring[0][0] > self.RING_SPAN:
            ring.popleft()
        n = len(ring)
        t1, x1, y1 = ring[-1]
        t0, x0, y0 = ring[-2]
        d = max(1e-4, t1 - t0)
        ix, iy = (x1 - x0) / d, (y1 - y0) / d
        if n >= 3:
            tm = xm = ym = 0.0
            for tt, xx, yy in ring:
                tm += tt
                xm += xx
                ym += yy
            tm /= n
            xm /= n
            ym /= n
            den = nx = ny = 0.0
            for tt, xx, yy in ring:
                dtt = tt - tm
                den += dtt * dtt
                nx += dtt * (xx - xm)
                ny += dtt * (yy - ym)
            den = max(den, 1e-9)
            lx, ly = nx / den, ny / den
        else:
            lx, ly = ix, iy
        si = math.hypot(ix, iy)
        sl = math.hypot(lx, ly)
        if ix * lx + iy * ly <= 0.0 or si < sl:       # slowing / turning: trust newest interval fully
            vx, vy = ix, iy
        else:                                         # speeding up: believe it only half-way
            vx, vy = lx + 0.5 * (ix - lx), ly + 0.5 * (iy - ly)
        sp = math.hypot(vx, vy)

        # 3) deceleration estimate (px/s^2, only the braking part is ever used)
        self._acc += self.ACC_EMA * ((sp - self._speed) / dt - self._acc)
        self._vx, self._vy, self._speed = vx, vy, sp
        if sp > 1e-6:
            self._ux, self._uy = vx / sp, vy / sp
        if sp > 25.0 * S:
            self._cux, self._cuy = self._ux, self._uy
        self._gi = _smoothstep(25.0 * S, 90.0 * S, sp)
        self._gl = _smoothstep(80.0 * S, 320.0 * S, sp)

    def _tick(self, now: float):
        """Advance the output to local time `now`. Caller holds _lock.
        Returns (x, y, quiet) or None if no sample has ever arrived."""
        if not self._have_out:
            return None
        dt = now - self._t_o
        if dt < 1e-4:
            dt = 1e-4
        elif dt > 0.1:
            dt = 0.1
        self._t_o = now

        gap = now - self._t_s
        if gap < 0.0:
            gap = 0.0
        gap0 = 1.35 * self._dt_ema + 0.012            # next sample is "overdue" after this
        p = 0.0 if gap <= gap0 else min(1.0, (gap - gap0) / 0.07)   # stop-detection ramp
        bx = self._fx + (self._rx - self._fx) * p     # base slides onto the LAST RAW sample
        by = self._fy + (self._ry - self._fy) * p

        sp = self._speed
        off = 0.0
        if sp > 1e-6 and p < 1.0:
            a = self.ACC_GAIN * self._acc if self._acc < 0.0 else 0.0
            tau = gap if gap < gap0 else gap0
            off = _extrap(sp, a, tau) * self._gi                              # interpolation
            if self._lead > 0.0:
                ld = (_extrap(sp, a, tau + self._lead) - _extrap(sp, a, tau)) * self._gl     # lead
                cap = self._lead_cap * self._S                                              # soft px cap
                off += cap * math.tanh(ld / cap)
            if gap > gap0:                                                    # overdue: damp, don't grow
                to = 0.04
                off += sp * to * (1.0 - math.exp(-(gap - gap0) / to)) * self._gi
            off *= 1.0 - p
        tx = bx + self._ux * off
        ty = by + self._uy * off

        # 6) follower: cutoff rises with speed (no lag when fast, no stairs when slow)
        fc = self._ff_min + 0.03 * sp / self._S
        if p > 0.0:
            fc = max(fc, 30.0)
        k = _lp(fc, dt)
        self._ox += (tx - self._ox) * k
        self._oy += (ty - self._oy) * k

        # 7) hard anti-overshoot guard along the last travel direction
        d_out = (self._ox - bx) * self._cux + (self._oy - by) * self._cuy
        d_tgt = (tx - bx) * self._cux + (ty - by) * self._cuy
        if d_tgt < 0.0:
            d_tgt = 0.0
        ex = d_out - d_tgt - 0.25
        if ex > 0.0:
            kk = 1.0 if (p > 0.0 or off <= 0.0) else 0.6
            self._ox -= self._cux * ex * kk
            self._oy -= self._cuy * ex * kk

        quiet = False
        if p >= 1.0:                                  # stopped: settle EXACTLY on the last sample
            if abs(tx - self._ox) < 0.08 and abs(ty - self._oy) < 0.08:
                self._ox, self._oy = tx, ty
                quiet = True
        if self._hold <= 0.0:
            return self._ox, self._oy, quiet
        # 8) rest hold (backlash): emit a point that trails the follower at <= r px.
        #    r is full while the hand is slow and fades to 0 between 1x and 3x the sensor
        #    noise speed, so a still hand is rock steady and a moving hand has no lag.
        if not self._b_ok:
            self._bx, self._by, self._b_ok = self._ox, self._oy, True
        r = self._hold * self._S * (1.0 - _smoothstep(self.V_DEAD * self._S, 3.0 * self.V_DEAD * self._S, sp))
        if p > 0.0:
            r = 0.0                                   # samples stopped on purpose: land exactly
        ddx, ddy = self._ox - self._bx, self._oy - self._by
        dd = math.hypot(ddx, ddy)
        if dd > r:
            k = (dd - r) / dd
            self._bx += ddx * k
            self._by += ddy * k
        return self._bx, self._by, quiet and dd <= r + 1e-6

    def advance(self, now: float):
        """Thread-safe single step (used by the emitter; handy for tests)."""
        with self._lock:
            return self._tick(now)

    def _emit(self, x: float, y: float) -> None:
        px = (int(round(x)), int(round(y)))
        if px == self._last_px:
            return
        self._last_px = px
        self._pos = (x, y)
        fn = self._fn
        if fn is not None:
            try:
                fn(x, y)
            except Exception:                         # never let a bad sink kill the emitter
                pass

    def _run(self) -> None:
        if sys.platform == "win32":                   # emitter must preempt inference/UI threads
            try:
                from .input_win32 import boost_thread_priority
                boost_thread_priority(2)
            except Exception:
                pass
        clock = self._clock
        sleep = time.sleep
        nxt = last = clock()
        while not self._stop.is_set():
            period = 1.0 / self._rate
            with self._emit_lock:
                with self._lock:
                    res = self._tick(clock())
                    if res is not None and res[2]:
                        self._wake.clear()            # nothing left to do until next ingest
                if res is not None:
                    self._emit(res[0], res[1])
            if res is None or res[2]:
                self._wake.wait(0.5)
                nxt = last = clock()
                continue
            t_now = clock()
            gap = t_now - last
            last = t_now
            self._ticks += 1
            if gap > self._gap_max:
                self._gap_max = gap
            if gap > 2.0 * period:
                self._late += 1
            nxt += period
            delay = nxt - clock()
            if delay > 0.0:
                sleep(delay)
            elif delay < -4.0 * period:
                nxt = clock()                         # fell behind: skip, don't burst

    # Windows: make sleep() precise (Python 3.11+ already uses high-res timers; this is a belt)
    def _enable_hires_timer(self) -> None:
        if sys.platform == "win32" and not self._timer_raised:
            try:
                import ctypes
                ctypes.windll.winmm.timeBeginPeriod(1)
                self._timer_raised = True
            except Exception:
                pass

    def _disable_hires_timer(self) -> None:
        if self._timer_raised:
            try:
                import ctypes
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass
            self._timer_raised = False


# =============================================================================
# self-test:  python motion.py
# =============================================================================
def _selftest() -> None:
    import random
    import numpy as np

    class Clk:                                        # fake clock => deterministic, instant
        t = 0.0

        def __call__(self) -> float:
            return self.t

    def jittery_caps(t_end, hz=30.0, jit=0.15, seed=1):
        rnd, caps, t = random.Random(seed), [], 0.0
        while t <= t_end:
            caps.append(t)
            t += (1.0 / hz) * (1.0 + rnd.uniform(-jit, jit))
        return caps

    def simulate(m, clk, path, caps, latency=0.03, hz=150.0, t_end=3.0):
        """Deliver samples at capture+latency, tick the emitter at `hz`.
        Returns (tick_times, xs, delivery_times)."""
        ev = sorted((c + latency, c) for c in caps)
        ei, tick, ts, xs = 0, 0.0, [], []
        while tick < t_end:
            while ei < len(ev) and ev[ei][0] <= tick:
                dl, c = ev[ei]
                clk.t = dl
                x, y = path(c)
                m.ingest(c, x, y)
                ei += 1
            clk.t = tick
            r = m.advance(tick)
            if r is not None:
                ts.append(tick)
                xs.append(r[0])
            tick += 1.0 / hz
        return np.array(ts), np.array(xs), [d for d, _ in ev]

    # ---- (a) smooth interpolation between samples (no 30 Hz stepping) --------
    clk = Clk()
    m = CursorMotion(clock=clk)
    v = 600.0
    caps = jittery_caps(2.5, jit=0.2, seed=5)
    ts, xs, deliv = simulate(m, clk, lambda t: (100.0 + v * t, 200.0), caps, t_end=2.6)
    sel = (ts > 0.6) & (ts < 2.2)
    steps = np.diff(xs[sel])
    cv = steps.std() / steps.mean()
    # what the old pipeline does: one move per frame, held in between
    hold = np.array([100.0 + v * max(c for c in caps if c + 0.03 <= t) for t in ts[sel]])
    hold_zero = float((np.diff(hold) == 0).mean())
    pxs = np.round(xs)
    per_interval = [len(set(pxs[(ts >= a) & (ts < b)])) for a, b in zip(deliv[8:-8], deliv[9:-7])]
    assert steps.min() > 0.0, "cursor stalled between samples"
    assert cv < 0.05, f"output stepping is uneven (CV={cv:.3f})"
    assert min(per_interval) >= 4, f"fewer than 4 distinct moves per sample interval: {min(per_interval)}"
    assert hold_zero > 0.5 and cv < 0.05 * hold_zero
    print(f"(a) interpolation  : step CV {cv:.3f} (30 Hz hold: {hold_zero:.0%} zero-length steps), "
          f">= {min(per_interval)} distinct pixels / sample interval")

    # ---- (b) stop behaviour: no overshoot, exact settle ----------------------
    def stop_run(kind, speed=900.0, seed=3, use_halt=False):
        clk = Clk()
        m = CursorMotion(clock=clk)
        t_run, x0 = 0.5, 100.0
        brake = {"ease": 0.25, "abrupt": None}[kind]

        def path(t):
            if brake is None or t <= t_run:
                return x0 + speed * t, 50.0
            u = min(1.0, (t - t_run) / brake)             # cosine-eased braking, then rest
            return x0 + speed * t_run + speed * brake * (u / 2 + math.sin(math.pi * u) / (2 * math.pi)), 50.0

        last_cap = 1.3 if brake else 0.9
        caps = jittery_caps(last_cap, jit=0.12, seed=seed)
        ts, xs, deliv = simulate(m, clk, path, caps, latency=0.04, t_end=2.5)
        final = path(caps[-1])[0]
        return m, ts, xs, deliv, final, t_run + (brake or 0.0)

    m, ts, xs, deliv, final, t_stop = stop_run("ease")
    brake_over = float((xs - final).max())               # overshoot during braking
    late = ts > t_stop + 0.04 + 0.034                    # hand stopped + pipeline latency + 1 frame
    post = xs[late] - final
    d_post = np.diff(np.abs(post))
    assert brake_over < 3.0, f"overshoot while braking: {brake_over:.2f}px"
    assert post.max() < 0.5, f"overshoot after stop: {post.max():.2f}px"
    assert (d_post <= 1e-6).all(), "wobble: error grew again after the stop"
    assert abs(xs[-1] - final) < 1e-9, "did not settle exactly on the last sample"
    print(f"(b) braking stop   : overshoot {max(brake_over, 0):.2f}px, post-stop {max(post.max(), 0):.2f}px, "
          f"monotone settle, final error {abs(xs[-1] - final):.1e}px")

    m, ts, xs, deliv, final, _ = stop_run("abrupt")      # samples just cease at 900 px/s
    after = ts > deliv[-1]
    err = xs[after] - final
    pk = int(np.argmax(err))
    assert err.max() <= 900.0 * (1.35 / 30 + 0.012 + 0.045), "run-on exceeds the dead-reckoning bound"
    assert (np.diff(err[pk:]) <= 1e-6).all(), "retract is not monotone (wobble)"
    assert abs(xs[-1] - final) < 1e-9 and m.advance(ts[-1] + 1.0)[2], "abrupt end did not settle"
    print(f"    samples cease  : bounded run-on {err.max():.1f}px, monotone retract, exact settle")

    clk = Clk()
    m = CursorMotion(clock=clk)                           # deliberate end of input -> halt()
    ts, xs, _ = simulate(m, clk, lambda t: (100.0 + 900.0 * t, 50.0), jittery_caps(0.6), t_end=0.62)
    at = m.advance(0.62)[0]
    clk.t = 0.62
    m.halt()
    later = [m.advance(0.62 + k / 150.0)[0] for k in range(1, 150)]
    assert max(abs(p - at) for p in later) < 1e-6, "halt() must freeze the cursor in place"
    print("    halt()         : cursor frozen in place, no run-on")

    # ---- (c) phase lag vs pure filtering on a sine path ----------------------
    F, A, LAT = 0.8, 250.0, 0.04
    path = lambda t: (500.0 + A * math.sin(2 * math.pi * F * t), 300.0)
    caps = jittery_caps(4.0, seed=1)

    def lag_ms(ts, xs):
        keep = ts > 1.0
        t, x = ts[keep], xs[keep]
        best = min(((float(np.sqrt(np.mean((x - (500 + A * np.sin(2 * np.pi * F * (t - d)))) ** 2))), d)
                    for d in np.arange(-0.08, 0.30, 0.0005)))
        now_rmse = float(np.sqrt(np.mean((x - (500 + A * np.sin(2 * np.pi * F * t))) ** 2)))
        return best[1] * 1000.0, now_rmse

    class OneEuroRef:                                    # the existing per-frame filter, verbatim logic
        def __init__(self, min_cutoff, beta, d_cutoff=1.2):
            self.mc, self.b, self.dc, self.x, self.dx, self.last = min_cutoff, beta, d_cutoff, None, None, None

        @staticmethod
        def _a(fc, dt):
            return 1.0 / (1.0 + (1.0 / (2 * math.pi * fc)) / dt)

        def __call__(self, v, t):
            dt = 1 / 60 if self.last is None else max(1e-3, t - self.last)
            self.last = t
            prev = v if self.x is None else self.x
            d = (v - prev) / dt
            self.dx = d if self.dx is None else self._a(self.dc, dt) * d + (1 - self._a(self.dc, dt)) * self.dx
            a = self._a(self.mc + self.b * abs(self.dx), dt)
            self.x = v if self.x is None else a * v + (1 - a) * self.x
            return self.x

    ref = OneEuroRef(min_cutoff=11.25, beta=1.0)         # make_filters(0.5): 30 Hz, one move per frame
    ev = sorted((c + LAT, c) for c in caps)
    vals = [(dl, ref(path(c)[0], dl)) for dl, c in ev]
    tr = np.arange(0.0, 4.0, 1 / 150.0)
    base = np.array([[v for dl, v in vals if dl <= t][-1] if t >= vals[0][0] else vals[0][1] for t in tr])
    lag_ref, rm_ref = lag_ms(tr, base)

    res = {}
    for pm in (0.0, 45.0):
        clk = Clk()
        m = CursorMotion(prediction_ms=pm, smoothness=0.5, clock=clk)
        ts, xs, _ = simulate(m, clk, path, caps, latency=LAT, t_end=4.0)
        res[pm] = lag_ms(ts, xs)
    (lag0, rm0), (lag1, rm1) = res[0.0], res[45.0]
    assert lag1 < lag_ref - 30.0 and lag1 < 0.4 * lag_ref, (lag1, lag_ref)
    assert rm1 < 0.5 * rm_ref and lag1 < lag0 - 15.0, (rm1, rm_ref, lag0)
    print(f"(c) sine lag       : pure 1-euro @30 Hz {lag_ref:.0f} ms / rmse {rm_ref:.0f}px  |  "
          f"smoothing only {lag0:.0f} ms  |  with prediction {lag1:.0f} ms / rmse {rm1:.0f}px")

    # ---- (d) speed-adaptive smoothing: steady at rest -------------------------
    rnd = random.Random(2)
    clk = Clk()
    m = CursorMotion(smoothness=0.5, clock=clk)
    raw, out, tick, t = [], [], 0.0, 0.0
    while t < 4.0:
        clk.t = t
        x = 500.0 + rnd.gauss(0, 2.0)
        raw.append(x)
        m.ingest(t, x, 400.0 + rnd.gauss(0, 2.0))
        t += 1 / 30.0
        while tick < t:
            clk.t = tick
            r = m.advance(tick)
            if r is not None and tick > 1.0:
                out.append(r[0])
            tick += 1 / 150.0
    assert np.std(out) < 0.55 * np.std(raw), (np.std(out), np.std(raw))
    print(f"(d) rest jitter    : {np.std(raw):.2f}px in -> {np.std(out):.2f}px out")

    # ---- threads: real clock, real emitter ------------------------------------
    got = []
    m = CursorMotion(max_rate=144.0)
    m.set_output(lambda x, y: got.append((time.perf_counter(), x, y)))
    m.start()
    t0 = time.perf_counter()
    for k in range(15):                                   # 0.5 s ramp @ 30 Hz, 400 px/s
        time.sleep(max(0.0, t0 + k / 30.0 - time.perf_counter()))
        tt = time.perf_counter()
        m.ingest(tt, 100.0 + 400.0 * (tt - t0), 300.0)
    time.sleep(0.6)                                       # input ended -> settles, emitter idles
    n_done = len(got)
    time.sleep(0.4)
    last_in = 100.0 + 400.0 * (tt - t0)
    pos = m.position
    m.stop()
    assert n_done >= 40, f"emitter produced only {n_done} moves"
    assert len(got) == n_done, "emitter kept running after settling"
    assert abs(pos[0] - last_in) < 1.0, (pos, last_in)
    print(f"(t) emitter thread : {n_done} moves for 15 samples, idles after settle, lands on last sample")
    print("all motion self-tests passed")


if __name__ == "__main__":
    _selftest()
