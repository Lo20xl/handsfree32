"""Signal smoothing: One Euro filter (cursor) + exponential EMA."""
import math
import time


def _alpha(cutoff, dt):
    tau = 1.0 / (2 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class _LowPass:
    def __init__(self):
        self.y = None

    def __call__(self, x, a):
        self.y = x if self.y is None else a * x + (1 - a) * self.y
        return self.y


class OneEuro:
    """1€ filter — low jitter when slow, low lag when fast.

    min_cutoff (Hz): lower = steadier at rest. beta: higher = less lag on fast moves.
    """

    def __init__(self, min_cutoff=8.0, beta=0.9, d_cutoff=1.2):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x = _LowPass()
        self._dx = _LowPass()
        self._last = None

    def filter(self, value, timestamp=None):
        t = timestamp if timestamp is not None else time.perf_counter()
        dt = 1 / 60 if self._last is None else max(1e-3, t - self._last)
        self._last = t
        prev = self._x.y if self._x.y is not None else value
        dx = (value - prev) / dt
        dx_hat = self._dx(dx, _alpha(self.d_cutoff, dt))
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        return self._x(value, _alpha(cutoff, dt))

    def reset(self):
        self._x = _LowPass()
        self._dx = _LowPass()
        self._last = None


def make_filters(smoothing):
    """Map the 0..0.95 UI smoothing setting to filter params."""
    s = min(0.95, max(0.0, float(smoothing)))
    min_cutoff = 20.0 - 17.5 * s      # 20 Hz (crisp) -> ~2.9 Hz (steady)
    beta = 0.4 + 1.2 * s              # more lead on fast motion when smoothed
    return OneEuro(min_cutoff=min_cutoff, beta=beta)


class OneEuroVec:
    """Per-axis 1€ filter (two independent OneEuro channels).

    The scalar OneEuro above is correct for a 1D signal; X/Y cursor motion is
    two independent signals, and the canonical open-source implementations
    (casiez/OneEuroFilter python + the MediaPipe/OpenXR vendored copies) filter
    each axis separately, so a diagonal move is not diluted by the other axis'
    smoothing. Kept here as the reference implementation for callers that need
    it and for the unit tests; the high-rate pipeline in motion.py uses the
    same maths inline with speed-adaptive cutoffs.
    """

    def __init__(self, min_cutoff=8.0, beta=0.9, d_cutoff=1.2):
        self.fx = OneEuro(min_cutoff, beta, d_cutoff)
        self.fy = OneEuro(min_cutoff, beta, d_cutoff)

    def filter(self, x, y, timestamp=None):
        return self.fx.filter(x, timestamp), self.fy.filter(y, timestamp)

    def reset(self):
        self.fx.reset()
        self.fy.reset()
