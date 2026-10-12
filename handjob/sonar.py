"""sonar.py - EXPERIMENTAL acoustic hand sensing (speaker -> microphone Doppler).

The laptop speaker emits a continuous inaudible tone (~19 kHz); hand movement
near the device reflects the tone with a Doppler shift (a hand moving 1 m/s
shifts a 19 kHz carrier by ~±110 Hz). The mic picture is an FFT around the
carrier each block; energy rising above the learned static leakage/floor =
hand motion, and which side is hotter says toward/away. This is the
SoundWave / AudioGest technique family (Microsoft Research 2012, and the 2026
MacBook sonar-scroller demo built with an OpenAI model).

    sensing ONLY: this module never drives the cursor or clicks. It is a
    diagnostic/secondary channel the app can surface and later build on.

Detection notes (why baseline tracking): a real tone leaks spectral energy
into the bins near the carrier (worst ~-40 dB with a Hann window at 4-8 bins),
and that leakage is STATIC — so the analyzer keeps a slow per-side baseline of
the sideband level and reports EXCESS over it. A deliberate hand wave raises
the sideband level 10-30 dB above the leakage, so 6 dB over baseline = motion.
Bins 6-30 from the carrier = 70-350 Hz Doppler = hand speeds ~0.5-2.5 m/s.

Hardware caveats: laptop speakers vary wildly - some roll off hard above
17 kHz (try the 17 kHz tone), and every device has its own mic noise floor.
The UI exposes tone + input/output device selection for that reason.

`python sonar.py --live [--tone N] [--seconds N]` runs a live check: make sure
the system default output/input are what you expect, then wave a hand near the
laptop and watch `score` (motion) / `direction` (toward +1 / away -1).
"""
from __future__ import annotations

import argparse
import logging
import math
import threading
import time

import numpy as np

log = logging.getLogger("handjob.sonar")

try:
    import sounddevice as sd
except Exception:  # noqa: BLE001 - headless / no-audio environments
    sd = None

BLOCK = 4096          # FFT block @ 48 kHz = 85 ms
EMIT_GAIN = 0.4       # playback amplitude (0..1)
SIDE_LO, SIDE_HI = 6, 34   # velocity window from the carrier (bins, ±70..±400 Hz)
FLOOR_LO, FLOOR_HI = 100, 220  # noise-floor reference band: 100-220 bins BELOW the carrier
MOTION_DB = 6.0       # excess over the learned baseline before "motion" (power dB)
FULL_DB = 18.0        # excess mapped to score 1.0
BASE_RATE = 0.02      # baseline EMA rate per quiet block (~4 s tau at ~12 blocks/s)
SPEED_OF_SOUND = 343.0  # m/s — Doppler conversion: Δf = 2·f0·v/c
CARRIER_MIN_DB = 10.0  # the carrier must be this far over the noise floor for the
                       # channel to work at all. Measured on a laptop whose
                       # speaker/mic pair cannot carry an ultrasonic tone: every
                       # tone from 17-20 kHz landed at <= +2.8 dB — the streams
                       # open fine and blocks analyse fine, but the mic hears only
                       # noise. Without this check the UI shows "motion 0.00"
                       # forever, which reads as a broken feature rather than
                       # unsupported hardware.


def analyze(block: np.ndarray, sr: int, tone: float, state: dict | None = None) -> dict:
    """Spectral analysis of one captured block, with a learned static baseline.

    `state` persists across calls (same dict reused); it holds the per-side
    baseline levels. Returns:
      carrier_db : carrier peak vs the far noise floor (dB) - "does the mic hear the tone"
      floor_db   : absolute noise floor - device diagnostics
      score      : 0..1 motion energy (sideband power excess over the learned baseline)
      direction  : +1 approaching / -1 receding / 0 (from the Doppler centroid)
      velocity   : signed Doppler speed in m/s (+ = toward the device); the
                   power-weighted centroid of the sideband window — steadier
                   than a max-bin pick and a real physical unit.

    Power-domain band energy (sum over the window) instead of max-bin: a single
    bin is a noisy estimator (Rayleigh fading); the summed window is far more
    stable at rest and the dB excess over baseline becomes repeatable.
    """
    n = len(block)
    if state is None:
        state = {}
    win = np.hanning(n)
    spec = np.abs(np.fft.rfft(block * win)) ** 2          # POWER spectrum
    eps = 1e-12
    k0 = tone * n / float(sr)
    if k0 < 3 or k0 > n / 2.0 - 3:
        raise ValueError(f"tone {tone} Hz out of range for sr {sr}")
    k0i = int(round(k0))
    # carrier: max of a ±2-bin window (the true peak may sit between bins)
    c_lo, c_hi = max(1, k0i - 2), min(len(spec) - 1, k0i + 2)
    carrier = float(np.max(spec[c_lo:c_hi + 1]))
    # noise floor: a quiet band well below the carrier (no hand sidebands there)
    f_hi = max(1, k0i - FLOOR_LO)
    f_lo = max(0, k0i - FLOOR_HI)
    floor = float(np.median(spec[f_lo:f_hi])) + eps
    floor_db = 10.0 * math.log10(floor)
    carrier_db = 10.0 * math.log10(carrier + eps) - floor_db
    # sideband windows just outside the leakage skirt (power sums)
    s_lo, s_hi = k0i + SIDE_LO, min(len(spec) - 1, k0i + SIDE_HI)
    l_lo, l_hi = max(1, k0i - SIDE_HI), max(1, k0i - SIDE_LO)
    up_band = spec[s_lo:s_hi + 1]
    down_band = spec[l_lo:l_hi + 1]
    p_up = float(np.sum(up_band)) if up_band.size else eps
    p_down = float(np.sum(down_band)) if down_band.size else eps
    up_db = 10.0 * math.log10(p_up + eps)
    down_db = 10.0 * math.log10(p_down + eps)
    # Doppler centroid -> signed velocity (m/s). Power-weighted mean bin offset
    # of the hotter side; the quieter side only supplies a negative baseline.
    vel = 0.0
    if p_up > p_down * 1.5 and up_band.size:
        bins = np.arange(s_lo, s_hi + 1, dtype=np.float64)
        off_bins = float(np.sum(bins * up_band) / (p_up + eps)) - k0
        vel = off_bins * sr / n * SPEED_OF_SOUND / (2.0 * tone)
    elif p_down > p_up * 1.5 and down_band.size:
        bins = np.arange(l_lo, l_hi + 1, dtype=np.float64)
        off_bins = float(np.sum(bins * down_band) / (p_down + eps)) - k0
        vel = off_bins * sr / n * SPEED_OF_SOUND / (2.0 * tone)
    # learned baselines (seed on first block; track drift while quiet).
    # Startup robustness: the first 10 blocks seed the baseline from their
    # MEDIAN, so flipping the toggle while already moving a hand cannot leave
    # a stuck-high baseline. Asymmetric drift after that: pulls DOWN fast
    # (a one-off loud event must not stick), pulls up slowly (leakage drift).
    if "seed" not in state:
        state["seed"] = []
    if len(state["seed"]) < 10:
        state["seed"].append((up_db, down_db))
        state["base_up"] = float(np.median([s[0] for s in state["seed"]]))
        state["base_down"] = float(np.median([s[1] for s in state["seed"]]))
        return {"carrier_db": carrier_db, "floor_db": floor_db, "score": 0.0,
                "direction": 0, "velocity": 0.0}
    eu, ed = up_db - state["base_up"], down_db - state["base_down"]
    excess = max(eu, ed)
    score = min(1.0, max(0.0, (excess - MOTION_DB) / (FULL_DB - MOTION_DB)))
    direction = 0
    if excess > MOTION_DB:
        if vel > 0.15:
            direction = 1
        elif vel < -0.15:
            direction = -1
    if excess < MOTION_DB - 2.0:
        r = BASE_RATE
        state["base_up"] += (r * 3.0 if up_db < state["base_up"] else r) * (up_db - state["base_up"])
        state["base_down"] += (r * 3.0 if down_db < state["base_down"] else r) * (down_db - state["base_down"])
    return {"carrier_db": carrier_db, "floor_db": floor_db, "score": score,
            "direction": direction, "velocity": vel}


class Sonar:
    """Continuous tone out, block FFT in, live diag dict out. Sensing only."""

    def __init__(self, in_dev: int = -1, out_dev: int = -1, tone: int = 19000):
        if sd is None:
            raise RuntimeError("sounddevice not available")
        self.in_dev = None if in_dev is None or int(in_dev) < 0 else int(in_dev)
        self.out_dev = None if out_dev is None or int(out_dev) < 0 else int(out_dev)
        self.tone = float(tone)
        self.key = (in_dev, out_dev, tone)
        self._stop = threading.Event()
        self._emit_i = 0
        self._latest = None
        self._latest_seq = 0        # bumped by the input callback per block
        self._last_seq = -1         # last block this loop analysed
        self._lock = threading.Lock()
        self._thread = None
        self._out = None
        self._in = None
        self._sr = 0
        self._blocks = 0
        self._state: dict = {}
        self.start_error = None       # set when start_async() fails
        self.diag = {"score": 0.0, "direction": 0, "carrier_db": 0.0, "floor_db": 0.0,
                     "velocity": 0.0, "sr": 0, "tone": tone, "blocks": 0}

    # ------------------------------------------------------------------ start
    def start(self):
        """Open the tone output + analysis input. Raises on any failure; the
        caller decides what to do (the engine retries with backoff)."""
        if sd is None:
            raise RuntimeError("sounddevice not available")
        # -1/None = system default: resolve to a real index first —
        # query_devices(None) returns the whole DeviceList, not a dict
        out_idx = self.out_dev
        if out_idx is None:
            try:
                out_idx = int(sd.default.device[1])
            except Exception:
                out_idx = -1
        if out_idx is None or int(out_idx) < 0:
            raise RuntimeError("no default output device for the sonar tone")
        out_idx = int(out_idx)
        in_idx = self.in_dev
        if in_idx is None:
            try:
                in_idx = int(sd.default.device[0])
            except Exception:
                in_idx = -1
        if in_idx is None or int(in_idx) < 0:
            raise RuntimeError("no default input device for the sonar mic")

        # Sample rate comes from the INPUT device and BOTH streams must open at
        # it. Deriving it from the output (the old code) opened the input at the
        # speaker's rate: whenever the mic's native rate differed (44.1k mic +
        # 48k speaker is common) PortAudio refused the input stream and the
        # sonar died with an opaque "Unanticipated host error" — it looked like
        # broken hardware, not a rate mismatch.
        sr = int(sd.query_devices(in_idx).get("default_samplerate") or 0)
        if not sr:
            sr = int(sd.query_devices(out_idx).get("default_samplerate") or 48000)
        if sr < int(self.tone * 2.2):
            raise RuntimeError(f"input device sample rate {sr} can't carry a "
                               f"{self.tone:.0f} Hz tone (needs >= {self.tone*2.2:.0f})")
        self._sr = sr
        buf = np.sin(2.0 * math.pi * self.tone * np.arange(sr) / sr).astype(np.float32)
        self._buf = buf

        def out_cb(outdata, frames, t, status):
            i = self._emit_i
            outdata[:, 0] = self._buf[(i + np.arange(frames)) % sr] * EMIT_GAIN
            self._emit_i = (i + frames) % sr

        def in_cb(indata, frames, t, status):
            with self._lock:
                self._latest = indata[:, 0].copy()
                self._latest_seq += 1

        try:
            self._out = sd.OutputStream(samplerate=sr, channels=1, dtype="float32",
                                        blocksize=BLOCK, device=out_idx, callback=out_cb)
            self._out.start()
            self._in = sd.InputStream(samplerate=sr, channels=1, dtype="float32",
                                      blocksize=BLOCK, device=in_idx, callback=in_cb)
            self._in.start()
        except Exception:
            self.stop()
            raise
        if self._stop.is_set():
            # the owner gave up while we were still opening (a wedged PortAudio
            # call can take seconds) — don't leave live streams behind
            self.stop()
            raise RuntimeError("sonar start aborted")
        self._thread = threading.Thread(target=self._run, name="HJ3-Sonar", daemon=True)
        self._thread.start()

    def start_async(self):
        """Start on a private thread. `start()` opens two PortAudio streams and
        that can block for tens of ms — calling it on the engine thread stalled
        the cursor loop the moment the sonar was enabled."""
        th = threading.Thread(target=self._start_guarded, name="HJ3-SonarBoot", daemon=True)
        th.start()
        return th

    def _start_guarded(self):
        try:
            self.start()
        except Exception as e:
            self.start_error = f"{type(e).__name__}: {e}"
            log.warning("sonar start failed: %s", self.start_error)

    # ------------------------------------------------------------------- loop
    def _run(self):
        while not self._stop.is_set():
            time.sleep(1.0 / 30.0)
            with self._lock:
                block, seq = self._latest, self._latest_seq
            # Only analyse a NEW block. The callback delivers one every
            # BLOCK/sr (~85 ms = ~11.8/s) while this loop polls at 30 Hz, so
            # without the sequence check the SAME block was re-analysed ~2.5x:
            # the baseline EMA advanced 2.5x too fast (its ~4 s tau became
            # ~1.6 s, so real leakage drift was never tracked and quiet reads
            # ratcheted the baseline down into false motion), and the 0.65/0.35
            # display smoothing made a single motion block look sustained.
            if block is None or len(block) != BLOCK or seq == self._last_seq:
                continue
            self._last_seq = seq
            try:
                d = analyze(block, self._sr, self.tone, self._state)
            except Exception:
                log.exception("sonar analyze failed")
                continue
            self._blocks += 1
            d["sr"] = self._sr
            d["tone"] = self.tone
            d["blocks"] = self._blocks
            # Is the mic actually hearing the tone? Judged only once the baseline
            # has seeded (the first 10 blocks), so a slow start can't false-alarm.
            d["carrier_ok"] = (self._blocks > 12
                               and d.get("carrier_db", 0.0) >= CARRIER_MIN_DB)
            d["score"] = 0.65 * self.diag["score"] + 0.35 * d["score"]   # display smoothing
            d["velocity"] = 0.6 * self.diag.get("velocity", 0.0) + 0.4 * d["velocity"]
            if d["direction"] == 0 and d["score"] > 0.1:
                d["direction"] = self.diag["direction"]                  # hold direction briefly
            self.diag = d

    # ------------------------------------------------------------------ stop
    def stop(self):
        self._stop.set()
        th = self._thread
        if th is not None and th is not threading.current_thread():
            th.join(timeout=1.5)
        self._thread = None
        for s in (self._in, self._out):
            try:
                if s is not None:
                    s.stop()
                    s.close()
            except Exception:
                pass
        self._in = self._out = None

    def status(self) -> str:
        d = self.diag
        if not d.get("sr"):
            return "sonar: initializing"
        if d.get("blocks", 0) > 12 and not d.get("carrier_ok", True):
            return (f"sonar: {d['tone']:.0f} Hz tone is NOT audible to the mic "
                    f"(carrier only +{d['carrier_db']:.0f} dB over the floor, "
                    f"needs +{CARRIER_MIN_DB:.0f}) — this speaker/mic pair cannot "
                    f"carry an ultrasonic tone; try another tone or device")
        return (f"sonar: {d['tone']:.0f} Hz @ {d['sr']} Hz | carrier +{d['carrier_db']:.0f} dB "
                f"above floor | motion {d['score']:.2f} (dir {d['direction']:+d}) "
                f"| v {d.get('velocity', 0.0):+.2f} m/s")


# =============================================================================
# self-test / live check:  python sonar.py [--live] [--tone 19000] [--seconds 12]
# =============================================================================
def _selftest() -> None:
    """Synthetic check of analyze(): a clean carrier reads as still AFTER the
    baseline learns its leakage; a Doppler sideband reads as motion with the
    right direction; the reading recovers when the motion stops."""
    sr, n, tone = 48000, BLOCK, 19000.0
    t = np.arange(n) / sr
    rng = np.random.default_rng(3)
    carrier = np.sin(2 * math.pi * tone * t)

    def noisy(x):
        return (x + rng.normal(0, 0.002, n)).astype(np.float32)

    state: dict = {}
    first = analyze(noisy(carrier * 0.4), sr, tone, state)
    assert first["carrier_db"] > 30, first
    for _ in range(30):                                   # baseline settles over ~30 blocks
        quiet = analyze(noisy(carrier * 0.4), sr, tone, state)
    assert quiet["score"] < 0.2, f"clean carrier must settle to still: {quiet}"
    assert quiet["direction"] == 0, quiet

    appr = noisy(carrier * 0.4 + np.sin(2 * math.pi * (tone + 110) * t) * 0.09)
    a = analyze(appr, sr, tone, state)
    assert a["score"] > 0.25 and a["direction"] == 1, a
    # Doppler centroid: +110 Hz at 19 kHz ≈ +1.0 m/s (2·f0·v/c)
    assert a["velocity"] > 0.4, f"approach velocity wrong: {a}"

    rec = noisy(carrier * 0.4 + np.sin(2 * math.pi * (tone - 110) * t) * 0.09)
    r = analyze(rec, sr, tone, state)
    assert r["score"] > 0.25 and r["direction"] == -1, r
    assert r["velocity"] < -0.4, f"recede velocity wrong: {r}"

    for _ in range(40):                                   # motion stops -> reading recovers
        back = analyze(noisy(carrier * 0.4), sr, tone, state)
    assert back["score"] < 0.2, f"reading must recover after motion: {back}"
    print(f"sonar analyze: quiet {quiet['score']:.2f} | approach {a['score']:.2f} dir {a['direction']:+d} "
          f"v {a['velocity']:+.2f} | recede {r['score']:.2f} dir {r['direction']:+d} v {r['velocity']:+.2f} "
          f"| recovered {back['score']:.2f}")
    _selftest_block_dedup()
    print("all sonar self-tests passed")


def _selftest_block_dedup() -> None:
    """The analysis loop must analyse each captured block ONCE.

    PortAudio delivers a block every BLOCK/sr (~85 ms, ~11.8/s) while the loop
    polls at 30 Hz, so re-analysing whenever the buffer merely still exists ran
    the same block through ~2.5x: the baseline EMA advanced 2.5x too fast (its
    ~4 s tau became ~1.6 s, so quiet reads ratcheted the baseline down into
    false motion) and the 0.65/0.35 display smoothing made one motion block
    look sustained. Feed blocks at 1/3 the poll rate and count the analyses.
    """
    global sd
    import numpy as np

    class FakeSonar(Sonar):
        """Sonar with PortAudio replaced: the real analysis loop runs unchanged,
        a feeder thread publishes blocks at ~1/3 the poll rate."""

        def __init__(self, blocks):
            super().__init__()
            self._feed = blocks

        def start(self):                      # no PortAudio
            self._sr = 48000
            self._thread = threading.Thread(target=self._run, name="HJ3-Sonar", daemon=True)
            self._thread.start()
            self._feeder = threading.Thread(target=self._feed_blocks, name="HJ3-SonarFeed",
                                            daemon=True)
            self._feeder.start()

        def _feed_blocks(self):
            for blk in self._feed:
                with self._lock:
                    self._latest = blk
                    self._latest_seq += 1     # the audio callback only bumps on a NEW block
                for _ in range(3):            # 30 Hz loop vs ~11.8 Hz blocks
                    time.sleep(1.0 / 30.0)
                    if self._stop.is_set():
                        return
            time.sleep(0.3)

    n = BLOCK
    sr, tone = 48000, 19000.0
    t = np.arange(n) / sr
    n_blocks = 30
    blocks = [(np.sin(2 * math.pi * tone * t) * 0.4).astype(np.float32) for _ in range(n_blocks)]

    # `Sonar.__init__` refuses to exist when sounddevice is missing, and the
    # import itself fails in a non-interactive session (PortAudio needs the
    # user's desktop) — but this logic touches no audio at all, so a sentinel
    # is enough to build the object.
    saved_sd, sd = sd, object()
    try:
        s = FakeSonar(blocks)
        s.start()
        s._feeder.join(timeout=30.0)
        s._thread.join(timeout=5.0)
        analysed = s.diag.get("blocks", 0)
        s.stop()
    finally:
        sd = saved_sd
    assert analysed == n_blocks, \
        f"each block must be analysed exactly once: {analysed} analyses for {n_blocks} blocks"
    print(f"block dedup: {analysed} analyses for {n_blocks} blocks "
          f"(presented for 3 polls each) — no re-analysis")

def _live(seconds: float, tone: int) -> None:
    if sd is None:
        print("sounddevice unavailable — cannot run a live check")
        return
    print(f"live sonar check: tone {tone} Hz for {seconds:.0f}s")
    print("  -> wave your hand 10-30 cm from the laptop (slowly toward/away) and watch the numbers")
    print("  -> no laptop speakers? try --tone 17000, or pick devices in the app's Sonar card")
    s = Sonar(tone=tone)
    s.start()
    try:
        t0 = time.time()
        while time.time() - t0 < seconds:
            d = s.diag
            bar = "#" * int(d["score"] * 40)
            print(f"  carrier {d['carrier_db']:6.1f} dB | motion {d['score']:.2f} {bar:<40} "
                  f"dir {d['direction']:+d} v {d.get('velocity', 0.0):+5.2f} m/s | blocks {d['blocks']}")
            time.sleep(0.5)
    finally:
        s.stop()
    print("SONAR_LIVE_DONE")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="live mic/speaker check (needs real hardware)")
    ap.add_argument("--tone", type=int, default=19000)
    ap.add_argument("--seconds", type=float, default=12.0)
    args = ap.parse_args()
    _selftest()
    if args.live:
        _live(args.seconds, args.tone)
