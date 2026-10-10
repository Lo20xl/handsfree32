"""HandJob3000 test suite — pure logic + a real inference test when a camera/model is present.

Run:  .venv/Scripts/python.exe -m tests.test_handjob            (unit only)
      .venv/Scripts/python.exe -m tests.test_handjob --full     (adds sample-image inference)
"""
import math
import sys

# ---------------------------------------------------------------- gestures ---
from handjob.gestures import (Pinch, ClickGesture, TravelMapper, ScrollAccumulator,
                              fingers_extended, classify_pose, palm_scale, dist,
                              track_point, pos_ago, palm_center, PrimaryHandSelector,
                              disambiguate_pinches)


def test_pinch_lifecycle():
    p = Pinch(threshold=0.4, sustain=0.09)
    e, l, held = p.update(0.9, 0.0)          # far
    assert not (e or l or held)
    e, l, held = p.update(0.30, 0.1)         # close begins
    assert not e, "should not enter before sustain"
    e, l, held = p.update(0.30, 0.21)        # still close, past sustain -> enter
    assert e and held
    e, l, held = p.update(0.45, 0.3)         # inside hysteresis band -> still held
    assert held and not l
    e, l, held = p.update(0.9, 0.4)          # released
    assert l and not held


def test_pinch_debounce_short_blip():
    p = Pinch(threshold=0.4, sustain=0.09)
    p.update(0.30, 1.00)                     # blip below sustain
    e, l, held = p.update(0.9, 1.05)         # back far before sustain elapsed
    assert not e and not held, "a quick blip must not click"


def test_click_left_down_on_enter_up_on_exit():
    g = ClickGesture(threshold=0.4)
    assert g.update_left(0.9, 0.0) == []
    g.update_left(0.3, 0.1)
    assert g.update_left(0.3, 0.2) == ["left_down"]
    assert g.update_left(0.3, 0.5) == []
    assert g.update_left(0.9, 0.6) == ["left_up"]


def test_right_click_single_fire_per_pinch():
    g = ClickGesture(threshold=0.4)
    assert g.update_right(0.9, 0.0) == []
    assert g.update_right(0.3, 0.10) == []
    assert g.update_right(0.3, 0.18) == [], "needs confirm delay"
    assert g.update_right(0.3, 0.19) == ["right_click"]
    assert g.update_right(0.3, 0.50) == [], "must not re-fire while held"
    assert g.right_held, "ring pinch must freeze the cursor while held"
    g.update_right(0.9, 0.6)                  # release
    g.update_right(0.3, 0.7)
    assert g.update_right(0.3, 0.80) == ["right_click"], "re-arms after release"


def test_right_click_cooldown():
    """Two ultra-rapid right pinches: the second is swallowed by the cooldown."""
    g = ClickGesture(threshold=0.4, right_cooldown=0.4)
    t0 = 100.0                      # non-zero base: 0.0 is the "no timestamp" sentinel
    g.update_right(0.3, t0)
    assert g.update_right(0.3, t0 + 0.10) == ["right_click"]
    g.update_right(0.9, t0 + 0.12)  # quick release
    g.update_right(0.3, t0 + 0.15)  # re-pinch almost immediately
    assert g.update_right(0.3, t0 + 0.30) == [], "cooldown must swallow the rapid second pinch"


def test_disambiguate_pinches():
    # left-only pinch passes through
    assert disambiguate_pinches(0.25, 0.90, 0.42) == (0.25, 1.0)
    # right-only pinch passes through
    assert disambiguate_pinches(0.90, 0.30, 0.42) == (1.0, 0.30)
    # both under threshold, left clearly closer -> left wins
    assert disambiguate_pinches(0.20, 0.40, 0.42) == (0.20, 1.0)
    # both under threshold, nearly equal -> neither fires (ambiguous)
    assert disambiguate_pinches(0.30, 0.33, 0.42) == (1.0, 1.0)
    # neither under threshold -> unchanged
    assert disambiguate_pinches(0.9, 0.9, 0.42) == (0.9, 0.9)


def test_mapper_center_clamps_and_tracks():
    m = TravelMapper(sensitivity=0.6)
    m.update_center(0.5, 0.5, 1 / 30)
    x, y = m.to_screen(0.5, 0.5, 1920, 1080)
    assert abs(x - 959.5) < 40 and abs(y - 539.5) < 40, "center maps to screen center"
    x0, y0 = m.to_screen(0.0, 0.0, 1920, 1080)
    x1, y1 = m.to_screen(1.0, 1.0, 1920, 1080)
    assert (x0, y0) == (0.0, 0.0) and (x1, y1) == (1919.0, 1079.0), "clamped to screen"
    # sensitivity: higher -> smaller span -> more px per normalized unit
    m2 = TravelMapper(sensitivity=0.9)
    assert m2.span < m.span


def test_scroll_accumulator():
    s = ScrollAccumulator(pixels_per_notch=0.02)
    assert s.update(0.5, True, 1.0) == 0     # first sample = baseline
    n = s.update(0.54, True, 1.0)            # +0.04 -> 2 notches
    assert n == 2, f"expected 2 notches, got {n}"
    s.update(0.54, False)                    # inactive resets
    assert s.update(0.20, True, 1.0) == 0, "baseline after re-activation"
    n = s.update(0.14, True, 1.0)            # -0.06 -> -3 notches
    assert n == -3, f"expected -3, got {n}"
    n = s.update(0.10, True, 1.0, invert=True)  # -0.04 * invert -> +2
    assert n == 2, f"invert failed: {n}"


def test_scroll_deadzone_swallows_jitter():
    s = ScrollAccumulator(pixels_per_notch=0.02, deadzone=0.005)
    s.update(0.5, True, 1.0)
    total = 0
    for i in range(20):                      # 20 tiny ±0.004 wobbles
        total += s.update(0.5 + (0.004 if i % 2 else 0.0), True, 1.0)
    assert total == 0, f"jitter must not scroll (got {total} notches)"


def test_pinch_is_not_scroll():
    """A pinch in progress (middle finger brushing the thumb) must stay 'point',
    never classify as the peace-sign scroll pose."""
    lm = _hand(True, False, False, False)
    assert classify_pose(lm, pinching=True) == "point"
    assert classify_pose(lm, pinching=False) == "point", "curled middle = plain point"


def _hand(index_ext=True, middle_ext=False, ring_ext=False, pinky_ext=False):
    """Synthetic hand: wrist at origin, MCP at (0.5, 0) for a known palm scale."""
    lm = [(0.0, 0.0, 0.0)] * 21
    lm[0] = (0.1, 0.9, 0)                     # wrist
    lm[9] = (0.5, 0.75, 0)                    # middle MCP -> palm scale ~0.427
    # index: straight up = extended; curled = tip near palm
    lm[5] = (0.42, 0.7, 0); lm[6] = (0.42, 0.5, 0)
    lm[8] = (0.42, 0.32, 0) if index_ext else (0.42, 0.62, 0)
    lm[9] = (0.5, 0.7, 0); lm[10] = (0.5, 0.5, 0)
    lm[12] = (0.5, 0.32, 0) if middle_ext else (0.5, 0.62, 0)
    lm[13] = (0.58, 0.7, 0); lm[14] = (0.58, 0.5, 0)
    lm[16] = (0.58, 0.32, 0) if ring_ext else (0.58, 0.62, 0)
    lm[17] = (0.66, 0.7, 0); lm[18] = (0.66, 0.5, 0)
    lm[20] = (0.66, 0.32, 0) if pinky_ext else (0.66, 0.62, 0)
    # thumb
    lm[3] = (0.2, 0.8, 0); lm[4] = (0.25, 0.72, 0)
    return lm


def test_fingers_and_pose():
    palm = palm_scale(_hand())
    assert palm > 0.3
    ext = fingers_extended(_hand(index_ext=True))
    assert ext[1] and not ext[2] and not ext[3] and not ext[4]
    # 4200 scheme: open palm = idle, point = point, peace sign = scroll
    assert classify_pose(_hand(True, True, True, True)) == "idle", "open palm rests"
    assert classify_pose(_hand(True, False, False, False)) == "point"
    assert classify_pose(_hand(True, True, False, False)) == "scroll"
    assert classify_pose(_hand(False, False, False, False)) == "idle", "fist rests"


def test_pinky_out_is_always_idle():
    """A relaxed half-open hand (pinky sticking out) must never drive the cursor,
    whatever the other fingers do."""
    assert classify_pose(_hand(True, False, False, True)) == "idle"
    assert classify_pose(_hand(True, True, False, True)) == "idle"
    assert classify_pose(_hand(True, True, True, True)) == "idle"


def test_natural_fist_is_idle_not_click():
    """4200: a fist classifies idle — the click machines are only fed in point
    pose, so a fist (which wraps the thumb near the fingers) can never click."""
    lm = _hand(False, False, False, False)
    lm[3] = (0.30, 0.72, 0)
    lm[4] = (0.40, 0.60, 0)   # thumb tip right next to the curled fingers
    assert classify_pose(lm) == "idle"


def test_track_point_is_index_tip():
    lm = _hand(True)
    assert track_point(lm) == (lm[8][0], lm[8][1])


def test_track_point_stable_during_click_pinch():
    """The aim point (index tip) must NOT move when a CLICK pinch sweeps the
    middle/ring fingers toward the thumb; whole-hand motion still moves it."""
    lm_open = _hand(True, False, False, False)
    x0, y0 = track_point(lm_open)
    lm_pinch = _hand(True, False, False, False)
    lm_pinch[4] = (0.30, 0.62, 0)   # thumb tip...
    lm_pinch[12] = (0.32, 0.63, 0)  # ...meets the middle tip (left-click pinch)
    x1, y1 = track_point(lm_pinch)
    assert abs(x1 - x0) < 1e-9 and abs(y1 - y0) < 1e-9, "pinch must not move the aim point"
    lm_shift = _hand(True, False, False, False)
    for i in (5, 8, 9, 13, 17):     # whole hand moves, including the aim tip
        lm_shift[i] = (lm_shift[i][0] + 0.1, lm_shift[i][1])
    x2, y2 = track_point(lm_shift)
    assert x2 > x1 + 0.05, "whole-hand motion must move the aim point"


def test_pos_ago_lookback():
    hist = [(0.0, 10, 10), (0.05, 20, 20), (0.10, 30, 30)]
    # oldest entry within the 0.12 s window = the position ~0.12 s ago
    assert pos_ago(hist, 0.20, 0.12, (0, 0)) == (30, 30)
    assert pos_ago(hist, 0.32, 0.12, (-1, -1)) == (-1, -1), "window empty -> fallback"


# ---------------------------------------------------- primary hand selector ---
def test_primary_selector_sticks_to_first_hand():
    sel = PrimaryHandSelector()
    # hand A appears at t=0
    assert sel.select([(0.2, 0.5)], 0.0) == 0
    # A + intruder B appears further right; A must stay primary (index 0)
    assert sel.select([(0.2, 0.5), (0.8, 0.5)], 0.1) == 0
    # only B remains -> no match, selector returns None (grace period)
    assert sel.select([(0.8, 0.5)], 0.2) is None, "intruder must not steal during grace"
    # B still there, still inside grace -> still None
    assert sel.select([(0.8, 0.5)], 0.5) is None
    # grace expired -> first hand present is adopted (A is gone for good)
    assert sel.select([(0.8, 0.5)], 0.2 + PrimaryHandSelector().grace + 0.01) == 0


def test_primary_selector_reappearing_hand_resumes():
    sel = PrimaryHandSelector()
    sel.select([(0.4, 0.5)], 0.0)
    # hand drops for a moment (detector blip)
    assert sel.select([], 0.1) is None
    # same hand reappears near the last anchor within grace -> resumes, not stolen
    assert sel.select([(0.41, 0.51), (0.9, 0.9)], 0.3) == 0


def test_palm_center_pose_independent():
    lm_open = _hand(True, True, True, True)
    lm_fist = _hand(False, False, False, False)
    c1, c2 = palm_center(lm_open), palm_center(lm_fist)
    assert abs(c1[0] - c2[0]) < 1e-9 and abs(c1[1] - c2[1]) < 1e-9, \
        "palm center must not change when fingers curl"


# ------------------------------------------------------------------ engine ---
def test_process_hand_pose_gates_cursor():
    """idle (open palm/fist) must freeze the cursor; point must move it."""
    import time as _t
    from handjob.engine import Engine, CursorBus
    from handjob import gestures as G
    from handjob import settings as S
    from handjob.click_refiner import ClickRefiner
    bus = CursorBus()
    e = Engine(bus)
    e.motion.start()
    e.arm(True)
    mapper = G.TravelMapper(0.6)
    clicks = ClickRefiner(0.42)
    scroll = G.ScrollAccumulator()
    cfg = dict(S.DEFAULTS)
    now = _t.time()
    try:
        e._process_hand(_hand(True, True, True, True), mapper, clicks, scroll, cfg, now, None)   # open palm
        _t.sleep(0.15)
        assert bus.position is None, "open palm must not move the cursor"
        # PoseTracker enters "point" on the 3rd steady frame (2 frames + 60 ms dwell);
        # keep feeding steady pointing until the debounce opens and the emitter lands.
        for k in range(5):
            e._process_hand(_hand(True, False, False, False), mapper, clicks, scroll,
                            cfg, now + 0.1 + k * 0.05, None)  # point
            _t.sleep(0.1)
        assert e.pose_tr.pose == "point", "steady pointing must pass the debounce"
        assert bus.position is not None, "pointing must move the cursor"
    finally:
        e.motion.stop()
    # a natural fist must NOT press the left button (phantom drag guard)
    bus2 = CursorBus()
    e2 = Engine(bus2)
    clicks2 = ClickRefiner(0.42)
    lm_fist = _hand(False, False, False, False)
    lm_fist[3] = (0.30, 0.72, 0); lm_fist[4] = (0.40, 0.60, 0)
    for i in range(8):
        e2._process_hand(lm_fist, mapper, clicks2, scroll, cfg, now + i * 0.05, None)
    assert not clicks2.left_down, "fist must not hold the left button"


def test_click_lock_holds_anchor_until_drag():
    """While a click pinch is held, the cursor stays at the press anchor; a
    movement past the drag threshold frees it into a drag."""
    import time as _t
    from handjob.engine import Engine, CursorBus
    from handjob import gestures as G
    from handjob import settings as S
    from handjob.click_refiner import ClickRefiner
    import handjob.engine as engmod
    calls = []
    buttons = []
    orig = engmod.wi.move_absolute
    orig_btn = engmod.wi.button
    engmod.wi.move_absolute = lambda x, y: calls.append((x, y))
    engmod.wi.button = lambda which, down: buttons.append((which, down))
    try:
        bus = CursorBus()
        e = Engine(bus)
        e.motion.start()
        mapper = G.TravelMapper(0.6)
        clicks = ClickRefiner(0.42)
        scroll = G.ScrollAccumulator()
        cfg = dict(S.DEFAULTS)
        e.arm(True)
        now = 100.0
        lm = _hand(True, False, False, False)
        # a few plain point frames (build history), then pinch the middle finger
        for i in range(4):
            e._process_hand(lm, mapper, clicks, scroll, cfg, now + i * 0.04, None)
        lm_pinched = _hand(True, False, False, False)
        lm_pinched[4] = (0.30, 0.62, 0)
        lm_pinched[12] = (0.32, 0.63, 0)
        for i in range(5):
            e._process_hand(lm_pinched, mapper, clicks, scroll, cfg, now + 0.2 + i * 0.04, None)
        _t.sleep(0.25)
        assert clicks.left_down, "sustained middle pinch must press the button"
        assert buttons[-1] == ("left", True), "left button must actually be pressed"
        ax, ay = clicks.anchor
        assert abs(calls[-1][0] - ax) < 1.5 and abs(calls[-1][1] - ay) < 1.5, \
            f"cursor must be snapped to the anchor, got {calls[-1]} vs ({ax:.1f},{ay:.1f})"
        anchor = calls[-1]
        # small hand wobble << press radius: cursor must stay at the anchor.
        # (~8 px mapped; the held-pinch radius has shrunk to ~12 px by the last
        # frame, so this stays inside it.)
        wobble = _hand(True, False, False, False)
        wobble[8] = (0.4212, 0.3212, 0)        # index tip +0.0012
        wobble[4] = (0.3012, 0.6212, 0)
        wobble[12] = (0.3212, 0.6312, 0)
        for i in range(4):
            e._process_hand(wobble, mapper, clicks, scroll, cfg, now + 0.4 + i * 0.04, None)
        _t.sleep(0.2)
        assert clicks.state != "drag", "small wobble must stay a click, not a drag"
        assert calls[-1] == anchor, \
            f"cursor must stay locked at the press anchor, moved to {calls[-1]}"
        # big move: drag unlocks and the cursor follows
        drag = _hand(True, False, False, False)
        drag[8] = (0.50, 0.32, 0)              # +0.08 normalized ~= many px
        drag[4] = (0.38, 0.62, 0)
        drag[12] = (0.40, 0.63, 0)
        e._process_hand(drag, mapper, clicks, scroll, cfg, now + 0.6, None)
        _t.sleep(0.25)
        assert clicks.state == "drag", "past the drag threshold the refiner must unlock"
        assert calls[-1] != anchor, "past the drag threshold the cursor must follow"
    finally:
        engmod.wi.move_absolute = orig
        engmod.wi.button = orig_btn


def test_click_refiner_reseed_drops_stale_history():
    """Claude-review fix: when the mapping teleports on purpose (re-anchor),
    reseed() must drop the old-mapping position history, so a pinch already
    closed at re-engage can't anchor the click at stale coordinates."""
    from handjob.click_refiner import ClickRefiner
    rf = ClickRefiner(0.28)
    t = 1.0
    for _ in range(10):                                # history under the OLD mapping
        rf.observe(t, 1500.0, 500.0)
        t += 1 / 30.0
    rf.reseed(t, 400.0, 500.0)                          # re-anchor teleported the mapping
    t += 1 / 30.0
    events = []
    for r in [0.12, 0.12, 0.12, 0.12]:                  # pinch ALREADY closed on re-engage
        rf.observe(t, 400.0, 500.0)
        events += rf.update_left(r, t) + rf.update_right(1.0, t)
        rf.cursor_target(t)
        t += 1 / 30.0
    assert "left_down" in events, events
    assert rf.anchor is not None
    assert abs(rf.anchor[0] - 400.0) < 2.0 and abs(rf.anchor[1] - 500.0) < 2.0, \
        f"anchor {rf.anchor} must come from the post-reseed position, not stale history"


def test_engine_reanchor_reseeds_click_anchor():
    """Claude-review fix, engine path: re-pointing with the pinch already
    closed right after a clutch reposition must anchor the click at the
    CURRENT cursor position (the re-anchor target), not at stale pre-re-anchor
    mapped coordinates."""
    import time as _t
    from handjob.engine import Engine, CursorBus
    from handjob import gestures as G
    from handjob import settings as S
    from handjob.click_refiner import ClickRefiner
    import handjob.engine as engmod
    calls, buttons = [], []
    orig = engmod.wi.move_absolute
    orig_btn = engmod.wi.button
    engmod.wi.move_absolute = lambda x, y: calls.append((x, y))
    engmod.wi.button = lambda which, down: buttons.append((which, down))
    try:
        bus = CursorBus()
        e = Engine(bus)
        e.motion.start()
        e.arm(True)
        mapper = G.TravelMapper(0.6)
        clicks = ClickRefiner(0.42)
        scroll = G.ScrollAccumulator()
        cfg = dict(S.DEFAULTS)
        now = _t.time()
        e.motion.snap(500.0, 500.0)                 # known cursor position
        assert calls[-1] == (500.0, 500.0)
        # clutch phase: idle (open palm) far left of the aim hand -> the refiner
        # accumulates history at OLD-mapping coordinates (clamped to x~0)
        idle = [(x - 0.30, y, z) for (x, y, z) in _hand(True, True, True, True)]
        for k in range(6):
            e._process_hand(idle, mapper, clicks, scroll, cfg, now + k * 0.05, None)
        # re-engage with the pinch ALREADY closed (thumb on middle finger)
        lm = _hand(True, False, False, False)
        lm[4] = (0.30, 0.62, 0); lm[12] = (0.32, 0.63, 0)
        pinched = [(x - 0.30, y, z) for (x, y, z) in lm]
        for k in range(6):
            e._process_hand(pinched, mapper, clicks, scroll, cfg, now + 0.4 + k * 0.05, None)
            _t.sleep(0.05)
        _t.sleep(0.15)
        assert ("left", True) in buttons, "pinch must press the button"
        assert abs(calls[-1][0] - 500.0) < 2.0 and abs(calls[-1][1] - 500.0) < 2.0, \
            f"click must land at the re-anchor target (500,500), got {calls[-1]}"
    finally:
        engmod.wi.move_absolute = orig
        engmod.wi.button = orig_btn


def test_cursor_deadzone_skips_repeats():
    """Whole-pixel repeats must not spam SendInput; real motion must still move."""
    import time as _t
    from handjob.engine import Engine, CursorBus
    from handjob import gestures as G
    from handjob import settings as S
    from handjob.click_refiner import ClickRefiner
    import handjob.engine as engmod
    calls = []
    orig = engmod.wi.move_absolute
    engmod.wi.move_absolute = lambda x, y: calls.append((x, y))
    try:
        bus = CursorBus()
        e = Engine(bus)
        e.motion.start()
        mapper = G.TravelMapper(0.6)
        clicks = ClickRefiner(0.42)
        scroll = G.ScrollAccumulator()
        cfg = dict(S.DEFAULTS)
        e.arm(True)
        now = _t.time()
        lm = _hand(True, False, False, False)
        # PoseTracker gate: steady "point" needs 2 frames + 60 ms dwell to open
        e._process_hand(lm, mapper, clicks, scroll, cfg, now, None)
        e._process_hand(lm, mapper, clicks, scroll, cfg, now + 0.07, None)
        _t.sleep(0.2)
        assert e.pose_tr.pose == "point", "steady pointing must pass the debounce"
        n1 = len(calls)
        assert n1 >= 1, f"pointing must move the cursor (got {n1})"
        for i in range(5):
            e._process_hand(lm, mapper, clicks, scroll, cfg, now + 0.1 + 0.05 * (i + 1), None)
        _t.sleep(0.15)
        assert len(calls) == n1, f"idle hand must not spam moves (got {len(calls)} vs {n1})"
        lm2 = _hand(True, False, False, False)
        for i in (5, 9, 13, 17):
            lm2[i] = (lm2[i][0] + 0.15, lm2[i][1])
        lm2[8] = (lm2[8][0] + 0.15, lm2[8][1])
        e._process_hand(lm2, mapper, clicks, scroll, cfg, now + 0.5, None)
        _t.sleep(0.25)
        assert len(calls) > n1, "real motion must still move the cursor"
    finally:
        engmod.wi.move_absolute = orig


def test_motion_interpolates_settles_and_halts():
    """CursorMotion: monotone inter-sample output, exact settle on the last
    sample (no overshoot wobble), halt() freezes in place."""
    from handjob.motion import CursorMotion

    class Clk:
        t = 0.0

        def __call__(self):
            return self.t

    clk = Clk()
    m = CursorMotion(clock=clk, prediction_ms=40)
    clk.t = 0.0
    m.ingest(0.0, 100.0, 200.0)
    clk.t = 0.05
    m.ingest(0.05, 200.0, 200.0)
    xs = []
    for k in range(1, 220):                        # drive well past the settle
        clk.t = 0.05 + k / 144.0
        r = m.advance(clk.t)
        if r is not None:
            xs.append(r[0])
    assert xs, "no output between samples"
    peak = max(xs)
    assert peak > 200.5, f"prediction must lead ahead of the last sample (peak {peak:.1f})"
    i_peak = xs.index(peak)
    after = xs[i_peak:]
    assert all(b <= a + 1e-6 for a, b in zip(after, after[1:])), \
        "retract must be monotone (no overshoot wobble)"
    settled = xs[-1]
    assert abs(settled - 200.0) < 0.01, f"did not settle on the last sample: {settled}"
    x_hold = settled
    m.halt()
    for k in range(10):
        r2 = m.advance(clk.t + 0.1 + k / 144.0)
    assert r2 is not None and abs(r2[0] - x_hold) < 1e-6, "halt must freeze the cursor"


def test_click_refiner_engine_api():
    """ClickRefiner provides the ClickGesture-compatible surface the engine
    uses (pinch.threshold, update_left/right events, anchor, properties)."""
    from handjob.click_refiner import ClickRefiner
    r = ClickRefiner(0.42)
    r.observe(0.00, 500.0, 300.0)
    assert r.update_left(0.9, 0.00) == []
    r.observe(0.05, 500.0, 300.0)
    assert r.update_left(0.30, 0.05) == [], "one frame must not click"
    r.observe(0.10, 500.0, 300.0)
    assert r.update_left(0.25, 0.10) == ["left_down"], "2nd sustained frame must press"
    assert r.left_down and r.anchor is not None
    r.observe(0.15, 500.0, 300.0)
    assert r.update_left(1.0, 0.15) == []
    r.observe(0.20, 500.0, 300.0)
    assert r.update_left(1.0, 0.20) == ["left_up"], "2nd open frame must release"
    assert not r.left_down
    assert r.release_all(0.3) == [], "release_all on a free refiner emits nothing"
    # right click fires once per pinch
    r2 = ClickRefiner(0.42)
    r2.observe(1.0, 100.0, 100.0)
    ev = []
    for i, ratio in enumerate([1.0, 0.9, 0.3, 0.2, 0.2, 0.2, 1.0, 1.0]):
        now = 1.0 + i / 30.0
        r2.observe(now, 100.0, 100.0)
        ev += r2.update_right(ratio, now)
        r2.update_left(1.0, now)
    assert ev.count("right_click") == 1, f"exactly one right click per pinch: {ev}"


def test_engine_has_motion_engine():
    """Engine builds a CursorMotion (settings smoothing) and stays live-tunable."""
    from handjob.engine import Engine, CursorBus
    e = Engine(CursorBus())
    assert e.motion is not None
    e.motion.configure(prediction_ms=30, smoothness=0.7, max_rate=120)  # must not raise
    assert e.motion.position is None


def test_snapshot_pulse_expires_and_prunes():
    import time as _t
    from handjob.engine import CursorBus
    bus = CursorBus()
    now = _t.time()
    bus.pulse = (100, 100, now - 0.5)
    assert bus.snapshot(now) is None, "stale pulse must expire and idle the overlay"
    bus.pulse = (100, 100, now - 0.1)
    assert bus.snapshot(now) is not None
    bus.pulse = None
    bus.particles = [(0, 0, 0, 0, now - 5.0, "star")]
    assert bus.snapshot(now) is None, "stale particles must be pruned"


def test_engine_motion_from_settings():
    """Engine's motion engine picks up the settings smoothing value and the
    virtual-screen speed scale (live-tunable via configure())."""
    from handjob.engine import Engine, CursorBus
    from handjob import settings as S
    e = Engine(CursorBus())
    s = float(S.get("smoothing"))
    assert 0.0 <= s <= 0.95
    e.motion.configure(smoothness=s)     # must not raise
    assert e.motion.position is None


# --------------------------------------------------------------- smoothing ---
from handjob.smoothing import OneEuro, make_filters


def test_one_euro_converges_and_dampens():
    f = OneEuro(min_cutoff=1.5, beta=0.1)
    t = 0.0
    for _ in range(240):
        t += 1 / 60
        y = f.filter(100.0, t)
    assert abs(y - 100.0) < 1.0, f"did not converge: {y}"
    # slow 0.5px jitter must be strongly damped (fast deliberate moves pass by design)
    outs = []
    for i in range(60):
        t += 1 / 60
        outs.append(f.filter(100.0 + (0.5 if i % 2 else 0.0), t))
    p2p = max(outs[-30:]) - min(outs[-30:])
    assert p2p < 0.30, f"jitter not damped: p2p={p2p}"
    hi = make_filters(0.9)._x
    lo = make_filters(0.0)
    assert hi is not None and lo is not None


# ----------------------------------------------------------------- settings ---
import os
import tempfile


def test_settings_clamp_and_roundtrip():
    from handjob import settings
    tmp = os.path.join(tempfile.gettempdir(), "hj4_settings_test.json")
    if os.path.exists(tmp):
        os.remove(tmp)
    settings.load(tmp)
    settings.set("sensitivity", 99)          # clamps to 1.0
    settings.set("click_threshold", 0.01)    # clamps to 0.20
    settings.set("cursor_style", "bogus")    # falls back to sky
    settings.save(tmp)
    settings.load(tmp)
    assert settings.get("sensitivity") == 1.0
    assert settings.get("click_threshold") == 0.15
    assert settings.get("cursor_style") == "sky"
    settings.reset()
    assert settings.get("sensitivity") == settings.DEFAULTS["sensitivity"]


# ------------------------------------------------------------------ overlay ---
def test_overlay_render_smoke():
    try:
        from PIL import Image
    except ImportError:
        print("  (skipped: pillow not installed)")
        return
    from handjob.overlay import render_frame, _premultiplied_bgra_bytes
    now = 1000.0
    view = dict(cursor=(100.0, 100.0), style="sky", dim=False, press=0.5,
                pulse=(100, 100, now - 0.1),
                trail=[(90, 95, now - 0.05), (95, 98, now - 0.02)],
                particles=[(110, 105, 50, -40, now - 0.1, "star"),
                           (105, 100, -30, 20, now - 0.05, "dot")])
    img = render_frame((300, 200), view, now)
    assert img.size == (300, 200) and img.mode == "RGBA"
    bbox = img.getbbox()
    assert bbox is not None, "cursor+trail should draw something"
    data = _premultiplied_bgra_bytes(img)
    assert len(data) == 300 * 200 * 4
    # premultiplied: no color channel may exceed alpha anywhere
    for i in range(0, len(data), 4):
        b, g, r, a = data[i], data[i + 1], data[i + 2], data[i + 3]
        assert b <= a and g <= a and r <= a, f"premultiply violated at {i}"


def test_premultiply_lut_matches_reference():
    """The LUT fast path must byte-match the uint16 reference premultiply."""
    import numpy as np
    from PIL import Image
    from handjob.overlay import _premultiplied_bgra
    rng = np.random.default_rng(7)
    arr = rng.integers(0, 256, (48, 64, 4), dtype=np.uint8)
    out = _premultiplied_bgra(Image.fromarray(arr, "RGBA"))
    a = arr[:, :, 3].astype(np.uint16)
    ref_b = (arr[:, :, 2].astype(np.uint16) * a // 255).astype(np.uint8)
    ref_g = (arr[:, :, 1].astype(np.uint16) * a // 255).astype(np.uint8)
    ref_r = (arr[:, :, 0].astype(np.uint16) * a // 255).astype(np.uint8)
    assert (out[:, :, 0] == ref_b).all()
    assert (out[:, :, 1] == ref_g).all()
    assert (out[:, :, 2] == ref_r).all()
    assert (out[:, :, 3] == arr[:, :, 3]).all()


def test_overlay_all_styles_render():
    try:
        from PIL import Image  # noqa
    except ImportError:
        return
    from handjob.overlay import render_frame
    for style in ("sky", "glow", "system"):
        img = render_frame((120, 90), dict(cursor=(60.0, 45.0), style=style, dim=True,
                                           press=0.0, trail=[], particles=[]), 5.0)
        assert img.getbbox() is not None or style == "system"


# ------------------------------------------- 2.5 overlay: dirty-rect + smoothness ---
def _rand_views(n=40, seed=11):
    import random
    rnd = random.Random(seed)
    t = 1000.0
    out = []
    for _ in range(n):
        cx, cy = rnd.uniform(60, 1860), rnd.uniform(60, 1020)
        view = dict(cursor=(cx, cy), style=rnd.choice(["sky", "glow", "system"]),
                    dim=rnd.random() < 0.3, press=rnd.choice([0.0, 0.4, 0.9]),
                    trail=[(cx - k * rnd.uniform(3, 30), cy + k * rnd.uniform(-9, 9), k * 0.025)
                           for k in range(rnd.randint(0, 18))],
                    particles=[(cx + rnd.uniform(-30, 30), cy + rnd.uniform(-30, 30),
                                rnd.uniform(-90, 90), rnd.uniform(-90, 90), t - rnd.uniform(0, 0.5),
                                rnd.choice(["star", "dot"])) for _ in range(rnd.randint(0, 6))],
                    pulse=(cx, cy, t - rnd.uniform(0, 0.3)) if rnd.random() < 0.4 else None)
        out.append((view, t))
    return out


def test_view_bounds_contains_every_drawn_pixel():
    """The dirty rect must never clip the sprite: render the whole desktop the
    OLD way and check every visible pixel lies inside view_bounds()."""
    from handjob.overlay import render_frame, view_bounds
    vs = (0, 0, 1920, 1080)
    for view, t in _rand_views():
        full = render_frame((1920, 1080), dict(view, origin=(0, 0)), t)
        bb = full.getbbox()
        b = view_bounds(view, vs, t)
        if bb is None:
            continue
        assert b is not None, "something was drawn but bounds said nothing"
        assert b[0] <= bb[0] and b[1] <= bb[1] and b[2] >= bb[2] and b[3] >= bb[3], (b, bb, view["style"])


def test_view_bounds_is_small_and_clamped():
    from handjob.overlay import view_bounds
    vs = (0, 0, 1920, 1080)
    v = dict(cursor=(960.0, 540.0), style="glow", trail=[], particles=[], pulse=None)
    x0, y0, x1, y1 = view_bounds(v, vs, 1.0)
    assert (x1 - x0) * (y1 - y0) < 0.01 * 1920 * 1080, "idle sprite should be well under 1% of the desktop"
    # off the top-left corner: clamped into the virtual screen, never negative
    v["cursor"] = (2.0, 3.0)
    b = view_bounds(v, vs, 1.0)
    assert b[0] == 0 and b[1] == 0
    # negative-origin multi-monitor desktop
    b = view_bounds(dict(v, cursor=(-1500.0, 400.0)), (-1920, 0, 3840, 1080), 1.0)
    assert b[0] >= -1920 and b[2] <= 1920
    assert view_bounds(dict(cursor=None, style="sky", trail=[], particles=[], pulse=None), vs, 1.0) is None
    assert view_bounds(dict(v, style="system"), vs, 1.0) is None, "system style draws no ring"


def test_supersampled_render_is_antialiased_and_same_geometry():
    import numpy as np
    from handjob.overlay import render_frame
    view = dict(cursor=(60.3, 45.7), style="glow", dim=False, press=0.0, trail=[], particles=[])
    a = np.asarray(render_frame((140, 100), view, 1.0, ss=1))
    b = np.asarray(render_frame((140, 100), view, 1.0, ss=2))
    # same footprint (within a pixel), and ss=2 has MANY more distinct alpha levels (smooth edges)
    ya, xa = np.nonzero(a[:, :, 3])
    yb, xb = np.nonzero(b[:, :, 3])
    assert abs(xa.min() - xb.min()) <= 2 and abs(xa.max() - xb.max()) <= 2
    assert abs(ya.min() - yb.min()) <= 2 and abs(ya.max() - yb.max()) <= 2
    assert len(np.unique(b[:, :, 3])) > len(np.unique(a[:, :, 3]))
    # a subpixel move must change the pixels at ss=2 (smooth motion), not snap
    c = np.asarray(render_frame((140, 100), dict(view, cursor=(60.8, 45.7)), 1.0, ss=2))
    assert (b != c).any()
    # nothing may be brighter than its alpha after the resize (no dark/white fringes)
    from PIL import Image
    from handjob.overlay import _premultiplied_bgra
    pm = _premultiplied_bgra(render_frame((140, 100), view, 1.0, ss=2))
    assert (pm[:, :, :3] <= pm[:, :, 3:4]).all()


def test_premultiply_into_matches_full_path():
    import numpy as np
    from PIL import Image
    from handjob.overlay import _premultiplied_bgra, _premultiply_into
    rng = np.random.default_rng(3)
    arr = rng.integers(0, 256, (40, 50, 4), dtype=np.uint8)
    img = Image.fromarray(arr, "RGBA")
    ref = _premultiplied_bgra(img)
    big = np.full((100, 120, 4), 77, dtype=np.uint8)           # garbage that must be overwritten
    view = big[20:60, 30:80]
    _premultiply_into(img, view)
    assert (view == ref).all()
    assert (big[:20] == 77).all() and (big[:, :30] == 77).all(), "wrote outside the sub-rectangle"


def test_overlay_dirty_rect_moves_without_ghosts():
    """Drive Overlay._draw with a fake compositor: the DIB must only ever hold
    the CURRENT sprite (old rect cleared) and each push covers a small rect."""
    import numpy as np
    import types
    from handjob import overlay as ov
    o = ov.Overlay.__new__(ov.Overlay)
    o._x, o._y, o._w, o._h = 0, 0, 1920, 1080
    o._dib = np.zeros((1080, 1920, 4), dtype=np.uint8)
    o._rect = None
    o._visible = False
    o._hwnd = 1
    pushed = []
    o._push = lambda rect: pushed.append(rect)
    saved = ov.user32
    ov.user32 = types.SimpleNamespace(ShowWindow=lambda *a: 1)
    try:
        v1 = dict(cursor=(300.0, 300.0), style="glow", dim=False, press=0.0, trail=[], particles=[], pulse=None)
        v2 = dict(v1, cursor=(1500.0, 800.0))
        assert o._draw(v1, 1.0) and o._visible
        assert o._dib[260:340, 260:340, 3].any()
        assert o._draw(v2, 1.0)
        assert not o._dib[:700, :1000, 3].any(), "ghost of the previous position left in the surface"
        assert o._dib[760:840, 1460:1540, 3].any()
        for (x0, y0, x1, y1) in pushed:
            assert (x1 - x0) * (y1 - y0) < 40_000, "frame touched far more than the sprite"
        v3 = dict(cursor=None, style="sky", trail=[], particles=[], pulse=None)
        assert o._draw(v3, 1.0) is False and not o._visible
        assert not o._dib[:, :, 3].any(), "hiding must leave a blank surface"
    finally:
        ov.user32 = saved


def test_overlay_frame_cost_is_tiny():
    """The whole point: per-frame CPU must not scale with the desktop size."""
    import time
    import numpy as np
    from handjob.overlay import render_frame, view_bounds, _premultiply_into
    for vs in ((0, 0, 1920, 1080), (0, 0, 3840, 2160)):
        dib = np.zeros((vs[3], vs[2], 4), dtype=np.uint8)
        view = dict(cursor=(vs[2] / 2.0, vs[3] / 2.0), style="glow", dim=False, press=0.0,
                    trail=[(vs[2] / 2.0 - k * 9, vs[3] / 2.0, k * 0.02) for k in range(24)],
                    particles=[], pulse=None)
        ts = []
        for _ in range(15):
            t0 = time.perf_counter()
            b = view_bounds(view, vs, 1.0)
            view["origin"] = (b[0], b[1])
            img = render_frame((b[2] - b[0], b[3] - b[1]), view, 1.0, ss=2)
            _premultiply_into(img, dib[b[1]:b[3], b[0]:b[2]])
            ts.append(time.perf_counter() - t0)
        ts.sort()
        med = ts[len(ts) // 2] * 1000.0
        assert med < 25.0, f"{vs[2]}x{vs[3]}: {med:.1f} ms per frame is too slow"


def test_bus_preview_long_poll():
    import threading
    import time
    from handjob.engine import CursorBus
    bus = CursorBus()
    assert bus.wait_preview(0, timeout=0.02) == (0, None), "nothing yet -> timeout, no frame"
    threading.Timer(0.03, lambda: bus.set_preview(b"\xff\xd8frame1")).start()
    t0 = time.perf_counter()
    seq, img = bus.wait_preview(0, timeout=0.5)
    assert seq == 1 and img and img.startswith("data:image/jpeg;base64,")
    assert time.perf_counter() - t0 < 0.3, "must wake on the new frame, not run out the timeout"
    assert bus.wait_preview(1, timeout=0.02) == (1, None), "same frame is never re-sent"


def test_bus_trail_and_wake_event():
    from handjob.engine import CursorBus
    bus = CursorBus()
    bus.visual_event.clear()
    bus.update_trail(1.0, 2.0, 5.0)
    assert bus.visual_event.is_set()
    for i in range(80):
        bus.update_trail(float(i), 0.0, 5.0 + i * 0.01)
    assert len(bus.trail) == 48


def test_capture_time_stamps_make_motion_smoother():
    """Why the engine now stamps frames at capture, not after inference: with
    10-25 ms of inference-time jitter in the timestamps the cursor ripples."""
    import random
    import numpy as np
    from handjob.motion import CursorMotion

    class Clk:
        t = 0.0

        def __call__(self):
            return self.t

    def run(stamp_at_capture):
        rnd = random.Random(3)
        clk = Clk()
        m = CursorMotion(prediction_ms=45, smoothness=0.55, clock=clk)
        path = lambda t: 960 + 600 * math.sin(2 * math.pi * 0.7 * t)
        ev, t = [], 0.0
        while t < 6.0:
            inf = max(0.004, rnd.gauss(0.016, 0.006))
            deliver = t + inf + 0.003
            ev.append((deliver, t if stamp_at_capture else deliver, path(t)))
            t += 1 / 30.0
        ei, tick, xs = 0, 0.0, []
        while tick < 6.0:
            while ei < len(ev) and ev[ei][0] <= tick:
                clk.t = ev[ei][0]
                m.ingest(ev[ei][1], ev[ei][2], 500.0)
                ei += 1
            clk.t = tick
            r = m.advance(tick)
            if r and tick > 1.0:
                xs.append(r[0])
            tick += 1 / 144.0
        return float(np.diff(np.diff(xs)).std())

    after, capture = run(False), run(True)
    assert capture < 0.7 * after, (capture, after)


# ------------------------------------------- 2.4.2 motion: rest-hold backlash ----------
def test_rest_hold_kills_jitter_without_motion_lag():
    """hold_px adds a backlash stage: emitted output trails the follower by at most
    r px while slow (sub-noise wobble never reaches the screen) and r collapses to
    0 with speed, so deliberate motion keeps zero lag."""
    import random
    from handjob.motion import CursorMotion

    class Clk:
        t = 0.0

        def __call__(self):
            return self.t

    def run_live(path, T, hold, seed=3):
        """Interleave like the real engine: 30 Hz samples in, 144 Hz emitter out.
        Returns the emitter's (x, y) stream over the whole run."""
        clk = Clk()
        m = CursorMotion(clock=clk, prediction_ms=0, smoothness=0.55, hold_px=hold)
        rnd = random.Random(seed)
        out = []
        t_in = 0.0
        t_out = 0.0
        while t_out < T:
            while t_in <= t_out:
                x, y = path(t_in)
                cx = 0.6 * getattr(run_live, "_cx", 0.0) + rnd.gauss(0, 0.004)
                cy = 0.6 * getattr(run_live, "_cy", 0.0) + rnd.gauss(0, 0.004)
                run_live._cx, run_live._cy = cx, cy
                m.ingest(t_in, x + cx * 200, y + cy * 200)   # sensor wobble on top of truth
                t_in += 1.0 / 30.0
            clk.t = t_out
            r = m.advance(t_out)
            if r:
                out.append(r[:2])
            t_out += 1.0 / 144.0
        run_live._cx = run_live._cy = 0.0
        return out

    def rest_wander(hold):
        run_live._cx = run_live._cy = 0.0
        out = run_live(lambda t: (960.0, 540.0), 5.0, hold)
        k = out[int(len(out) * 0.5):]                     # skip the engage transient
        xs = [p[0] for p in k]
        return max(xs) - min(xs)

    off, on = rest_wander(0.0), rest_wander(4.0)
    assert on < 0.5 * off, f"hold should roughly halve rest wander: {off:.1f} -> {on:.1f}"

    def sweep_err(hold):
        import math as _m
        out = run_live(lambda t: (960.0 + 300 * _m.sin(2 * _m.pi * 0.8 * t), 540.0),
                       5.0, hold)
        errs = []
        for i, (x, _y) in enumerate(out[int(len(out) * 0.6):]):
            t = 5.0 * 0.6 + (i + 1) / 144.0
            errs.append(abs(x - (960.0 + 300 * _m.sin(2 * _m.pi * 0.8 * t))))
        return sum(errs) / len(errs)

    assert sweep_err(4.0) < sweep_err(0.0) + 6.0, "hold must not add lag at speed"

    # disabled = legacy behaviour exactly
    clk = Clk()
    m = CursorMotion(clock=clk, prediction_ms=0, smoothness=0.55, hold_px=0.0)
    m.ingest(0.0, 100.0, 100.0)
    for i in range(200):
        r = m.advance((i + 1) / 144.0)
    assert r is not None and abs(r[0] - 100.0) < 0.5 and abs(r[1] - 100.0) < 0.5

    # clamp: out-of-range values are bounded
    clk = Clk()
    m = CursorMotion(clock=clk, hold_px=99.0)
    assert m._hold == 20.0
    m.configure(hold_px=-5)
    assert m._hold == 0.0


def test_engine_passes_hold_px_setting():
    """The engine wires settings.hold_px into the motion engine (construction path)."""
    import handjob.engine as engmod
    src = open(engmod.__file__, encoding="utf-8").read()
    assert 'hold_px=float(settings.get("hold_px") or 0.0)' in src
    assert 'hold_px=self._hold_seen' in src
    from handjob.settings import DEFAULTS
    assert DEFAULTS["hold_px"] == 2.5


# ------------------------------------------- 2.4.3 engine: frozen-camera watchdog ------
def test_frozen_cam_watchdog_state():
    """A live camera always yields new frames (sensor noise); <=2 unique/s means
    the source is frozen (virtual cam with a dead upstream). The watchdog must
    error after two checks, clear on recovery, and never fire on slow-but-live."""
    from handjob.engine import _frozen_cam_state, FROZEN_UNIQUE_FPS
    s, a = _frozen_cam_state(None, 0)
    assert (s, a) == (0, "ok"), "no measurement yet — stay quiet"
    s, a = _frozen_cam_state(0.2, 0)
    assert (s, a) == (1, "ok"), "first frozen window is a maybe"
    s, a = _frozen_cam_state(0.2, 1)
    assert (s, a) == (2, "error"), "two frozen windows = hard error"
    s, a = _frozen_cam_state(0.2, 5)
    assert (s, a) == (6, "error")
    s, a = _frozen_cam_state(30.0, 2)
    assert (s, a) == (0, "clear"), "live camera clears the frozen error"
    s, a = _frozen_cam_state(30.0, 0)
    assert (s, a) == (0, "ok"), "steady live camera stays quiet"
    s, a = _frozen_cam_state(8.0, 0)
    assert (s, a) == (0, "ok"), "slow but live (dim light) never errors"
    assert FROZEN_UNIQUE_FPS == 2.0
    from handjob.engine import FROZEN_ERR
    assert "Refresh app" in FROZEN_ERR and "frozen" in FROZEN_ERR


def test_engine_frozen_wiring():
    """The engine halts the cursor on frozen and clears on recovery."""
    import handjob.engine as engmod
    src = open(engmod.__file__, encoding="utf-8").read()
    assert "_frozen_cam_state(urate, self._frozen_streak)" in src
    assert "self.bus.error = FROZEN_ERR" in src and "self.motion.halt()" in src
    assert "self._frozen_streak = 0" in src            # reset on camera switch
    assert "self._frozen_streak < 2" in src            # reopen capped while frozen


# ------------------------------------------- 2.4.4 engine: repeat-frame dup gate ----
def test_dup_frame_gate():
    """Virtual cams answer every read by repeating the last frame (user's log:
    8.5 unique of 54.7 reads/s). Feeding repeats downstream puts 67 ms of real
    motion into an 18 ms dt -> inflated velocity -> the cursor lurches on each
    new frame. The engine must classify repeats with the same signature metric
    as the unique-frame watchdog and drop them before the pipeline."""
    import numpy as np
    from handjob.engine import _is_dup_sig, Engine

    frame = np.full((48, 64, 3), 90, dtype=np.uint8)
    frame[10:20, 10:30] = 200
    sig_a = Engine._frame_sig(frame)
    sig_b = Engine._frame_sig(frame.copy())
    assert _is_dup_sig(sig_b, sig_a), "identical frames must classify as duplicates"
    assert not _is_dup_sig(sig_b, None), "no history -> never a duplicate"
    moved = frame.copy()
    moved[12:22, 12:32] = 220              # visible content change
    assert not _is_dup_sig(Engine._frame_sig(moved), sig_a), \
        "a changed frame must pass the gate"

    # wiring: the gate is used in the loop and resets on camera switches,
    # and only real cameras (we-opened captures) are gated
    import handjob.engine as engmod
    src = open(engmod.__file__, encoding="utf-8").read()
    assert "_is_dup_sig(sig, self._last_proc_sig)" in src
    assert "self._last_proc_sig = None" in src
    assert "self._dedupe = self.capture is not None" in src


# --------------------------------------------------------- win32 constants ---
def test_win32_module_imports():
    from handjob import input_win32 as wi
    assert wi.LEFTDOWN and wi.RIGHTUP and wi.MOVE
    x0, y0, w, h = wi.virtual_screen()
    assert w > 0 and h > 0
    # don't ever actually move/click in tests


# -------------------------------------------------- inference (opt-in --full) ---
def test_inference_sample_image():
    import os
    import cv2
    from mediapipe import Image as MpImage, ImageFormat
    from handjob.engine import Engine, CursorBus
    from handjob.paths import assets_dir
    path = os.path.join(assets_dir(), "sample_hands.jpg")
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "woman_hands.jpg")
    img = cv2.imread(path)
    assert img is not None, f"test image missing: {path}"
    eng = Engine(CursorBus())
    eng._load_model()
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    res = eng.landmarker.detect_for_video(MpImage(image_format=ImageFormat.SRGB, data=rgb), 1)
    assert len(res.hand_landmarks) >= 1, "no hand detected in the sample image"
    lms = [(lm.x, lm.y, lm.z) for lm in res.hand_landmarks[0]]
    ratio = dist(lms[4], lms[12]) / palm_scale(lms)
    assert 0.0 < ratio < 3.0, f"pinch ratio out of range: {ratio}"
    eng.cleanup()


# -------------------------------------------------------------------- 2.1 ---
def test_edge_stabilizer_holds_and_releases():
    """EdgeStabilizer: hold inside the margin, hysteresis release band."""
    from handjob.hand3d import EdgeStabilizer
    e = EdgeStabilizer(margin=0.04, release=0.02)
    assert not e.update(0.5, 0.5), "center is stable"
    assert e.update(0.02, 0.5), "left edge must hold"
    assert e.update(0.5, 0.055), "inside the release band the hold persists (hysteresis)"
    assert e.update(0.5, 0.07) is False, "past the band the hold releases"
    assert e.update(0.5, 0.5) is False, "well clear stays released"
    assert e.update(0.99, 0.5) is True and e.update(0.5, 0.01) is True
    e.reset()
    assert e.holding is False


def test_engine_edge_hold_freezes_cursor():
    """Hand sliding into the frame corner must NOT drag the cursor along:
    the engine feeds the last stable aim point while the edge hold is active."""
    import time as _t
    from handjob.engine import Engine, CursorBus
    from handjob import gestures as G
    from handjob import settings as S
    from handjob.click_refiner import ClickRefiner
    import handjob.engine as engmod
    calls = []
    orig = engmod.wi.move_absolute
    orig_btn = engmod.wi.button
    engmod.wi.move_absolute = lambda x, y: calls.append((x, y))
    engmod.wi.button = lambda which, down: None

    def shifted(dx, dy):
        """Uniformly translate the synthetic hand — pose stays 'point'."""
        return [(x + dx, y + dy, z) for (x, y, z) in _hand(True, False, False, False)]

    try:
        bus = CursorBus()
        e = Engine(bus)
        e.motion.start()
        e.arm(True)
        mapper = G.TravelMapper(0.6)
        clicks = ClickRefiner(0.42)
        scroll = G.ScrollAccumulator()
        cfg = dict(S.DEFAULTS)
        now = _t.time()
        lm = _hand(True, False, False, False)      # aim tip at (0.42, 0.32)
        for k in range(8):                          # steady point -> cursor settles
            e._process_hand(lm, mapper, clicks, scroll, cfg, now + k * 0.05, None)
            _t.sleep(0.09)
        _t.sleep(0.2)
        n = len(calls)
        assert n >= 1, "pointing must move the cursor"
        lm_corner = shifted(-0.40, 0.60)            # tip lands at (0.02, 0.92): edge band
        assert e.edge.update(0.02, 0.92) is True, "tip must be inside the edge margin"
        e.edge.reset()                              # let the engine frame decide cleanly
        for k in range(8):
            e._process_hand(lm_corner, mapper, clicks, scroll, cfg, now + 0.4 + k * 0.05, None)
            _t.sleep(0.09)
        _t.sleep(0.2)
        assert calls[-1] == calls[n - 1], \
            f"edge hold must keep the cursor still: {calls[n-1]} -> {calls[-1]}"
        lm_center = shifted(0.13, 0.08)             # tip back at (0.55, 0.40): free
        for k in range(5):
            e._process_hand(lm_center, mapper, clicks, scroll, cfg, now + 1.0 + k * 0.05, None)
            _t.sleep(0.09)
        assert len(calls) > n, "cursor must move again once clear of the edge"
    finally:
        engmod.wi.move_absolute = orig
        engmod.wi.button = orig_btn


def test_sonar_analyze_synthetic():
    """sonar analyze(): static leakage settles to 'still'; a Doppler sideband
    reads as motion with the right direction; the reading recovers after."""
    import numpy as np
    from handjob.sonar import analyze, BLOCK
    sr, n, tone = 48000, BLOCK, 19000.0
    t = np.arange(n) / sr
    carrier = np.sin(2 * math.pi * tone * t)
    state: dict = {}
    for _ in range(30):                                  # baseline learns the leakage
        quiet = analyze((carrier * 0.4).astype(np.float32), sr, tone, state)
    assert quiet["carrier_db"] > 30, quiet
    assert quiet["score"] < 0.2, f"clean tone must read as still: {quiet}"
    appr = (carrier * 0.4 + np.sin(2 * math.pi * (tone + 110) * t) * 0.09).astype(np.float32)
    a = analyze(appr, sr, tone, state)
    assert a["score"] > 0.25 and a["direction"] == 1, a
    rec = (carrier * 0.4 + np.sin(2 * math.pi * (tone - 110) * t) * 0.09).astype(np.float32)
    r = analyze(rec, sr, tone, state)
    assert r["score"] > 0.25 and r["direction"] == -1, r


def test_engine_sonar_sync_disabled_is_inert():
    """_sync_sonar with the toggle off must never open an audio stream."""
    from handjob.engine import Engine, CursorBus
    e = Engine(CursorBus())
    e._sync_sonar({"sonar_enabled": False, "sonar_in_device": -1,
                   "sonar_out_device": -1, "sonar_tone": 19000})
    assert e.sonar is None


def test_sonar_start_resolves_default_devices():
    """Sonar.start() must resolve -1/None defaults to a real device index.

    Regression: query_devices(None) returns the whole DeviceList, so the old
    .get('default_samplerate') raised AttributeError when devices were left
    at 'System default' — the first thing every user does.
    """
    from types import SimpleNamespace
    from handjob import sonar as S

    calls = []

    class FakeSD:
        default = SimpleNamespace(device=[2, 5])

        @staticmethod
        def query_devices(idx=None):
            if idx is None:
                raise AssertionError("query_devices called without a resolved index")
            calls.append(idx)
            return {"default_samplerate": 48000}

        class OutputStream:
            def __init__(self, **kw):
                calls.append(("out", kw.get("device")))

            def start(self):
                pass

            def stop(self):
                pass

            def close(self):
                pass

        class InputStream(OutputStream):
            def __init__(self, **kw):
                calls.append(("in", kw.get("device")))

    orig = S.sd
    S.sd = FakeSD()
    try:
        s = S.Sonar(-1, -1, 19000)
        s.start()
        assert s._sr == 48000
        assert ("out", 5) in calls, calls          # default out index resolved, not -1
        s.stop()
    finally:
        S.sd = orig


def test_landmark_stabilizer_smooths_and_gates():
    """lmsmooth (2.2): rest jitter is reduced, a tracker teleport is clamped
    and recovers, and a real (slower) move is tracked without heavy lag."""
    import random
    from handjob.lmsmooth import LandmarkStabilizer

    def shifted(dx, dy, jx=0.0, jy=0.0):
        return [(x + dx + jx, y + dy + jy, z) for (x, y, z) in _hand(True, False, False, False)]

    st = LandmarkStabilizer()
    rnd = random.Random(5)
    raw, sm, t = [], [], 0.0
    for _ in range(70):
        t += 1 / 30.0
        lm = shifted(0.2, -0.3, rnd.uniform(-0.008, 0.008), rnd.uniform(-0.008, 0.008))
        out = st.process(lm, t)
        raw.append(lm[8][0]); sm.append(out[8][0])
    var = lambda v: sum((x - sum(v) / len(v)) ** 2 for x in v) / len(v)
    assert var(sm) < 0.5 * var(raw), (var(raw), var(sm))   # visibly steadier

    # teleport frame: clamped near the held position, then recovers
    held = sm[-1]
    out = st.process(shifted(0.6, -0.3), t + 1 / 30.0)
    assert abs(out[8][0] - held) < 0.15, (out[8][0], held)
    t += 2 / 30.0
    out = st.process(shifted(0.6, -0.3), t)
    assert out[8][0] > held + 0.05, "must follow the hand once the jump persists"

    # moderate move (2 palm/s): followed closely
    st2 = LandmarkStabilizer()
    t, dx = 0.0, 0.0
    for _ in range(15):
        t += 1 / 30.0
        st2.process(shifted(dx, 0.0), t)
    for _ in range(10):
        dx += 0.05
        t += 1 / 30.0
        out = st2.process(shifted(dx, 0.0), t)
    # compare against the true shifted position: no more than 0.2 palm behind
    true_x = _hand(True, False, False, False)[8][0] + dx
    assert true_x - out[8][0] < 0.2, (true_x, out[8][0])


def test_landmark_stabilizer_recovers_from_persistent_scale_change():
    """Claude-review fix: a palm-scale step that PERSISTS (hand leaned in,
    tracker re-locked at a new depth) must re-seed the filter within a couple
    of frames instead of holding the old frame forever (cursor frozen)."""
    from handjob.lmsmooth import LandmarkStabilizer

    def hand(cx, cy, palm=0.2):
        lm = [(cx, cy, 0.0)] * 21
        for i in range(1, 21):
            lm[i] = (cx + palm * (0.2 + 0.03 * i), cy + palm * (0.05 * (i % 5)), 0.0)
        lm[0] = (cx, cy, 0.0)
        lm[9] = (cx + palm, cy, 0.0)                     # palm length == palm
        lm[8] = (cx + 0.9 * palm, cy - 0.4 * palm, 0.0)  # index tip right of wrist
        return lm

    st = LandmarkStabilizer()
    t = 0.0
    for _ in range(10):
        t += 1 / 30.0
        st.process(hand(0.5, 0.5, 0.20), t)
    r0 = st._rejects
    out = None
    for k in range(10):
        t += 1 / 30.0
        out = st.process(hand(0.5 + 0.004 * k, 0.5, 0.30), t)   # new scale persists
    assert st._rejects - r0 <= 1, "a persistent change must re-seed after one held frame"
    true_x = 0.5 + 0.004 * 9 + 0.9 * 0.30
    assert abs(out[8][0] - true_x) < 0.05, (out[8][0], true_x)

    # a one-frame z-flip is still held (unchanged behavior)
    st2 = LandmarkStabilizer()
    t = 0.0
    out = None
    for _ in range(10):
        t += 1 / 30.0
        out = st2.process(hand(0.5, 0.5, 0.20), t)
    held = out[8][0]
    out = st2.process(hand(0.5, 0.5, 0.32), t + 1 / 30.0)
    assert abs(out[8][0] - held) < 0.02, "z-flip frame must be held"
    out = st2.process(hand(0.5, 0.5, 0.20), t + 2 / 30.0)
    assert abs(out[8][0] - held) < 0.05, "recovers on the next good frame"


def test_sonar_velocity_centroid():
    """sonar v2: the Doppler centroid reports signed velocity in m/s —
    ±110 Hz at 19 kHz is ±1.0 m/s (2·f0·v/c)."""
    import numpy as np
    from handjob.sonar import analyze, BLOCK
    sr, n, tone = 48000, BLOCK, 19000.0
    t = np.arange(n) / sr
    carrier = np.sin(2 * math.pi * tone * t)
    state: dict = {}
    for _ in range(25):                                   # seed + settle
        analyze((carrier * 0.4).astype(np.float32), sr, tone, state)
    appr = (carrier * 0.4 + np.sin(2 * math.pi * (tone + 110) * t) * 0.09).astype(np.float32)
    a = analyze(appr, sr, tone, state)
    assert a["direction"] == 1 and 0.5 < a["velocity"] < 1.5, a
    rec = (carrier * 0.4 + np.sin(2 * math.pi * (tone - 110) * t) * 0.09).astype(np.float32)
    r = analyze(rec, sr, tone, state)
    assert r["direction"] == -1 and -1.5 < r["velocity"] < -0.5, r


def test_snapshot_hides_orb_without_hand():
    """2.3: the overlay orb only renders while a hand is detected."""
    from handjob.engine import CursorBus
    bus = CursorBus()
    bus.armed = True
    bus.position = (500, 500)
    bus.found = False
    assert bus.snapshot() is None, "no hand -> no orb"
    bus.found = True
    s = bus.snapshot()
    assert s is not None and s["cursor"] == (500, 500)


def test_effective_prediction_scales_with_dt():
    """2.3: prediction never drops below ~1.4 camera intervals — at 30 fps the
    slider value wins (unchanged feel); at ~10 fps feeds it scales up so the
    emitter can interpolate across the gap instead of jumping per sample."""
    from handjob.engine import _effective_prediction
    assert _effective_prediction(45, 1 / 30) == 45        # 30 fps: slider wins
    assert abs(_effective_prediction(45, 1 / 10) - 130) < 1e-6   # 10 fps: scaled
    assert _effective_prediction(120, 1 / 30) == 120      # user value respected


def test_settings_21_keys():
    """New 2.1 settings clamp correctly (choices, ranges, bools)."""
    from handjob import settings as S
    assert S._clamp("capture_fps", 30) == 30
    assert S._clamp("capture_fps", 45) == 60            # invalid choice -> default
    assert S._clamp("max_hands", 2) == 2
    assert S._clamp("max_hands", 7) == 1
    assert S._clamp("edge_margin", 9) == 0.12
    assert S._clamp("sonar_tone", 19000) == 19000
    assert S._clamp("sonar_tone", 12345) == 19000
    assert S._clamp("sonar_enabled", "on") is True
    assert S._clamp("sonar_enabled", None) is False
    assert S._clamp("model_file", "  x.task  ") == "x.task"     # 2.4: trimmed string


def test_model_registry_and_resolution():
    """2.4: model picker registry — bundled default + imported .task files;
    resolution maps "" to the bundled asset and custom names to models/."""
    import os
    from handjob.engine import list_models, _task_path, MODEL_NAME, CUSTOM_MODELS_DIR
    from handjob.paths import app_dir, assets_dir
    ms = list_models()
    assert ms and ms[0]["file"] == "" and not ms[0]["custom"]
    assert _task_path("") == os.path.join(assets_dir(), MODEL_NAME)
    assert _task_path(MODEL_NAME) == os.path.join(assets_dir(), MODEL_NAME)
    assert _task_path("my_custom.task") == os.path.join(app_dir(), CUSTOM_MODELS_DIR, "my_custom.task")
    assert os.path.basename(_task_path("..\\evil\\x.task")) == "x.task", "path parts must be stripped"


def test_model_import_validates_and_copies():
    """2.4: import_model test-loads the file first and copies only valid .task
    files into models/; garbage and reserved names are rejected."""
    import os
    import tempfile
    from handjob.engine import import_model, list_models, MODEL_NAME, CUSTOM_MODELS_DIR
    from handjob.paths import app_dir, assets_dir
    fd, bad = tempfile.mkstemp(suffix=".task")
    os.write(fd, b"not a model")
    os.close(fd)
    try:
        import_model(bad)
        raise AssertionError("garbage must be rejected")
    except ValueError:
        pass
    ok = import_model(os.path.join(assets_dir(), MODEL_NAME), "test_copy.task")
    assert ok == "test_copy.task"
    try:
        assert "test_copy.task" in [m["file"] for m in list_models()]
    finally:
        try:
            os.remove(os.path.join(app_dir(), CUSTOM_MODELS_DIR, "test_copy.task"))
        except OSError:
            pass
    try:
        import_model(os.path.join(assets_dir(), MODEL_NAME), MODEL_NAME)
        raise AssertionError("reserved name must be rejected")
    except ValueError:
        pass


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    full = "--full" in sys.argv
    passed = failed = 0
    for t in tests:
        if t.__name__ == "test_inference_sample_image" and not full:
            print(f"skip  {t.__name__} (use --full)")
            continue
        try:
            t()
            passed += 1
            print(f"ok    {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e!r}")
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
