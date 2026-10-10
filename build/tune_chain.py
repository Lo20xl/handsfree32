"""Cursor smoothness harness — measures the full tracking pipeline
(landmark filter -> TravelMapper -> CursorMotion) on synthetic hand motion.

Replicates the review-harness scenarios so tuning decisions are made on
numbers, not vibes. Compares hold_px (rest-hold backlash) settings against
the pipeline with the stage disabled.

Scenarios: rest jitter, slow precise drift, sweep, eased stop, fine adjust.
Run:  .venv/Scripts/python.exe build/tune_chain.py [hold_px ...]
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


def hand(cx, cy):
    pts = []
    for i in range(21):
        a = i * 0.3
        r = PALM * (0.4 + 0.6 * (i % 3) / 2.0)
        pts.append([cx + r * math.cos(a), cy + r * math.sin(a), 0.0])
    pts[0] = [cx, cy, 0.0]
    pts[9] = [cx + PALM, cy, 0.0]
    pts[8] = [cx + 0.10, cy - 0.12, 0.0]        # index tip
    return pts


class Clk:
    t = 0.0

    def __call__(self):
        return self.t


def run(path, T, hold_px=0.0, fps=30.0, noise=0.002, rho=0.7, seed=1, lat=0.02, sens=0.6):
    """path(t)->(cx,cy) normalized hand pos. Returns ts, out_x, out_y, true_x, true_y (px)."""
    rnd = random.Random(seed)
    lm = LandmarkStabilizer()
    clk = Clk()
    m = CursorMotion(clock=clk, speed_scale=1.0, prediction_ms=45, smoothness=0.55,
                     hold_px=hold_px)
    mp = TravelMapper(sensitivity=sens)
    mp.center = [0.5, 0.5]
    ar = [[0.0, 0.0] for _ in range(21)]
    ev = []
    t = 0.0
    while t < T:
        cx, cy = path(t)
        h = hand(cx, cy)
        for i in range(21):
            for k in range(2):
                ar[i][k] = rho * ar[i][k] + math.sqrt(1 - rho * rho) * rnd.gauss(0, noise)
                h[i][k] += ar[i][k]
        tc = t + rnd.uniform(-0.001, 0.001)
        out = lm.process([tuple(p) for p in h], tc)
        sx, sy = mp.to_screen(out[8][0], out[8][1], W, H)
        ev.append((tc + lat + 0.012, tc, sx, sy))
        t += 1.0 / fps
    ei = 0
    tick = 0.0
    ts, xs = [], []
    while tick < T:
        while ei < len(ev) and ev[ei][0] <= tick:
            clk.t = ev[ei][0]
            m.ingest(ev[ei][1], ev[ei][2], ev[ei][3])
            ei += 1
        clk.t = tick
        r = m.advance(tick)
        if r:
            ts.append(tick)
            xs.append(r[0])
        tick += 1 / 144.0
    ts = np.array(ts)
    xs = np.array(xs)
    tru = np.array([mp.to_screen(path(t)[0] + 0.10, path(t)[1] - 0.12, W, H)[0] for t in ts])
    return ts, xs, tru


def best_lag(ts, x, tx, t0, t1, path_px):
    """RMSE-optimal output lag (ms) — the 'feels behind' number."""
    k = (ts > t0) & (ts < t1)
    best = (1e9, 0.0)
    for d in np.arange(0, 0.40, 0.004):
        ref = np.array([path_px(t - d) for t in ts[k]])
        e = float(np.sqrt(np.mean((x[k] - ref) ** 2)))
        if e < best[0]:
            best = (e, d)
    return best[1] * 1000, best[0]


def sstep(u):
    return 6 * u ** 5 - 15 * u ** 4 + 10 * u ** 3


def scenarios(hold_px, seeds=(1, 2, 3)):
    res = {k: [] for k in ("rest_sd", "rest_p2p", "slow_lag", "slow_stall",
                           "sweep_lag", "stop_over", "stop_settle", "fine_settle")}
    v = 40 / (1920 / (0.92 - 0.58 * 0.6))
    A, F = 0.16, 0.7
    for sd in seeds:
        # A rest
        ts, x, tx = run(lambda t: (0.5, 0.5), 5.0, hold_px, seed=sd)
        k = ts > 1.5
        res["rest_sd"].append(float(np.hypot(x[k] - x[k].mean(), 0).std()))
        res["rest_p2p"].append(float(np.ptp(x[k])))
        # B slow drift 40 px/s
        pf = lambda t: (0.5 + v * max(0, t - 1.0), 0.5)
        scr = lambda t: (0.5 + v * max(0, t - 1.0) + 0.10 - 0.5 + 0.286) / 0.572 * (W - 1)
        ts, x, tx = run(pf, 5.0, hold_px, seed=sd)
        lag, _ = best_lag(ts, x, tx, 2.0, 5.0, scr)
        res["slow_lag"].append(lag)
        kk = ts > 2.0
        xs_, tt = x[kk], tx[kk]
        n = int(0.1 * 144)
        stalls = tot = 0
        for i in range(0, len(xs_) - n, n):
            if abs(tt[i + n] - tt[i]) > 3.0:
                tot += 1
                stalls += abs(xs_[i + n] - xs_[i]) < 1.0
        res["slow_stall"].append(stalls / max(1, tot))
        # C sweep
        pf = lambda t: (0.5 + A * math.sin(2 * math.pi * F * t), 0.5)
        scr = lambda t: (0.5 + A * math.sin(2 * math.pi * F * t) + 0.10 - 0.5 + 0.286) / 0.572 * (W - 1)
        ts, x, tx = run(pf, 5.0, hold_px, seed=sd)
        lag, _ = best_lag(ts, x, tx, 1.5, 5.0, scr)
        res["sweep_lag"].append(lag)
        # D eased stop then rest
        pf = lambda t: (0.3 + 0.15 * sstep(min(max((t - 1.0) / 0.5, 0), 1.0)), 0.5)
        ts, x, tx = run(pf, 3.5, hold_px, seed=sd)
        fin = tx[-1]
        k2 = ts > 1.0
        res["stop_over"].append(float(max(0.0, (x[k2] - fin).max())))
        kk = ts > 1.5
        bad = np.nonzero(np.abs(x[kk] - fin) > 8.0)[0]
        res["stop_settle"].append(float((ts[kk][bad[-1]] - 1.5) * 1000) if len(bad) else 0.0)
        # E fine adjust after settle
        pf = lambda t: (0.5 + 0.012 * sstep(min(max((t - 2.0) / 0.3, 0), 1.0)), 0.5)
        ts, x, tx = run(pf, 4.0, hold_px, seed=sd)
        fin = tx[-1]
        kk = ts > 2.0
        bad = np.nonzero(np.abs(x[kk] - fin) > 8.0)[0]
        res["fine_settle"].append(float((ts[kk][bad[-1]] - 2.0) * 1000) if len(bad) else 0.0)
    return {k: float(np.mean(v)) for k, v in res.items()}


if __name__ == "__main__":
    holds = [float(a) for a in sys.argv[1:]] or [0.0, 1.5, 2.5, 4.0]
    print(f"{'hold':>5} | {'rest_sd':>7} {'p2p':>5} {'slowLag':>7} {'stall':>5} "
          f"{'swpLag':>6} {'over':>5} {'settle':>6} {'fine':>5}")
    for hp in holds:
        r = scenarios(hp)
        print(f"{hp:5.1f} | {r['rest_sd']:7.2f} {r['rest_p2p']:5.1f} {r['slow_lag']:7.0f} "
              f"{r['slow_stall']:5.2f} {r['sweep_lag']:6.0f} {r['stop_over']:5.1f} "
              f"{r['stop_settle']:6.0f} {r['fine_settle']:5.0f}")
