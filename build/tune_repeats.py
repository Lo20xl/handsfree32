"""Simulate a REPEATING camera (virtual cam / low-light auto-exposure).

The camera answers ~55 reads/s but only ~15 frames/s are genuinely new; the
rest are duplicates of the previous frame (this is what Camo / NVIDIA Broadcast
do, and it is what the user's log showed: "8.5 unique of 54.7 reads/s").

Two feeding strategies for the downstream pipeline
(landmark filter -> TravelMapper -> CursorMotion):

  A "every"  (shipped behaviour): duplicates are ingested as samples. Velocity
     is estimated over the READ interval (18 ms) while the motion actually
     accumulated over the UNIQUE interval (67 ms) -> velocity ~3.7x too high ->
     the 1-euro cutoff boost passes the jump almost unfiltered -> the cursor
     lurches each time a new frame lands. Between lurches it stalls. That is
     the "jitter / not smooth / delayed" feel.

  B "unique" (candidate fix): duplicates are dropped; the pipeline sees honest
     67 ms intervals: proper interpolation + prediction + smoothing.

Metrics on a constant-velocity glide (200 px/s screen):
  stepCV   relative std of per-tick advance (unevenness)
  lurch    worst single-tick advance error, px
  lag_ms   RMSE-optimal output lag (the "feels behind" number)
  rmse     best-matching RMSE, px
Run:  .venv/Scripts/python.exe build/tune_repeats.py
"""
import math
import random
import sys

import numpy as np

sys.path.insert(0, ".")
from handjob.gestures import TravelMapper
from handjob.lmsmooth import LandmarkStabilizer
from handjob.motion import CursorMotion

PALM = 0.15
W, H = 1920, 1080
READ_HZ = 55.0
UNIQ_HZ = 15.0


def hand(cx, cy):
    pts = []
    for i in range(21):
        a = i * 0.3
        r = PALM * (0.4 + 0.6 * (i % 3) / 2.0)
        pts.append([cx + r * math.cos(a), cy + r * math.sin(a), 0.0])
    pts[0] = [cx, cy, 0.0]
    pts[9] = [cx + PALM, cy, 0.0]
    pts[8] = [cx + 0.10, cy - 0.12, 0.0]
    return pts


class Clk:
    t = 0.0

    def __call__(self):
        return self.t


def run(mode, T=6.0, speed_px=200.0, noise=0.002, rho=0.7, seed=1,
        lat=0.02, sens=0.6):
    rnd = random.Random(seed)
    mp = TravelMapper(sensitivity=sens)
    mp.center = [0.5, 0.5]
    v_norm = speed_px * mp.span / (W - 1)

    def path(t):
        return 0.30 + v_norm * max(0.0, t - 1.0), 0.5

    # --- unique frames on a 15 Hz grid (jittered), reads on a 55 Hz grid ---
    frames = []                     # (t_capture, raw hand points) — unique only
    j = 0
    t = 0.0
    while t < T:
        cx, cy = path(rnd.uniform(max(0.0, t - 0.01), t + 0.01))
        frames.append((t, hand(cx, cy)))
        j += 1
        t = j / UNIQ_HZ
    reads = []                      # (t_read, newest available frame index)
    i = 0
    while True:
        t = i / READ_HZ
        if t >= T:
            break
        avail = [fi for fi, (tf, _) in enumerate(frames) if tf + lat <= t]
        reads.append((t, avail[-1] if avail else -1))
        i += 1

    lm = LandmarkStabilizer()
    clk = Clk()
    m = CursorMotion(clock=clk, speed_scale=1.0, prediction_ms=45, smoothness=0.55,
                     hold_px=2.5)
    ar = [[0.0, 0.0] for _ in range(21)]

    def noisy(fi):
        h = [list(p) for p in frames[fi][1]]
        for i2 in range(21):
            for k in range(2):
                ar[i2][k] = rho * ar[i2][k] + math.sqrt(1 - rho * rho) * rnd.gauss(0, noise)
                h[i2][k] += ar[i2][k]
        return [tuple(p) for p in h]

    lm_state = {"last": None}

    def process_read(fi, t_read):
        return lm.process(noisy(fi), t_read)

    ei = 0
    tick = 0.0
    ts, out_x = [], []
    while tick < T:
        while ei < len(reads) and reads[ei][0] <= tick:
            t_read, fi = reads[ei]
            if fi >= 0:
                if mode == "every":
                    lms = process_read(fi, t_read)
                    use = True
                elif fi != lm_state["last"]:
                    lms = process_read(fi, t_read)
                    lm_state["last"] = fi
                    use = True
                else:
                    use = False
                if use:
                    sx, sy = mp.to_screen(lms[8][0], lms[8][1], W, H)
                    clk.t = t_read
                    m.ingest(t_read, sx, sy)
            ei += 1
        clk.t = tick
        r = m.advance(tick)
        if r:
            ts.append(tick)
            out_x.append(r[0])
        tick += 1 / 144.0

    ts = np.array(ts)
    xx = np.array(out_x)
    k = (ts > 2.5) & (ts < 5.5)
    tsk, xk = ts[k], xx[k]
    d = np.diff(xk)
    dt = np.diff(tsk)
    ideal = speed_px * dt
    cv = float(np.std(d - ideal) / np.mean(ideal))
    mx = float(np.abs(d - ideal).max())
    best = (1e9, 0.0)
    for lag in np.arange(0, 0.4, 0.002):
        ref = np.array([mp.to_screen(path(t - lag)[0] + 0.10, path(t - lag)[1] - 0.12, W, H)[0] for t in tsk])
        e = float(np.sqrt(np.mean((xk - ref) ** 2)))
        if e < best[0]:
            best = (e, lag)
    return cv, mx, best[1] * 1000, best[0]


if __name__ == "__main__":
    print(f"{'mode':>8} | {'stepCV':>6} {'maxlurch':>9} {'lag_ms':>6} {'rmse_px':>7}   (avg of 3 seeds, 55 reads/s, 15 unique/s)")
    for mode in ("every", "unique"):
        cv, mx, lag, rmse = zip(*[run(mode, seed=s) for s in (1, 2, 3)])
        print(f"{mode:>8} | {np.mean(cv):6.3f} {np.mean(mx):9.2f} {np.mean(lag):6.0f} {np.mean(rmse):7.1f}")
