"""Gesture primitives: pinch state machines, pose classification, click semantics.

Pure logic (no mediapipe / no win32) so it is unit-testable.
Landmarks are (x, y, z) tuples in normalized frame coords.

HandJob3000 scheme (ported from the user's hand_mouse.py prototype):

  point   index extended, middle/ring/pinky curled -> cursor follows the
          index TIP — the point you actually aim with
  scroll  index + middle extended (peace sign) -> move hand up/down to scroll
  idle    open palm / fist / pinky out / hand gone -> cursor frozen ("clutch")

  LEFT click   thumb + middle pinch while pointing (raw mouse semantics:
               down on enter, up on exit; quick pinch = click, hold & move = drag)
  RIGHT click  thumb + ring pinch while pointing (fires once per pinch)

Click-stability design (the "polish" parts of the prototype):
  * clicks use middle/ring — fingers that are NOT aiming — so the aim point
    (index tip) never moves while clicking;
  * a click lands where the cursor was ~0.12 s ago (the hand wobbles as the
    fingers move; the lookback position is what the user meant to hit);
  * on press the cursor locks to that anchor until the hand moves past a drag
    threshold -> clean click vs drag separation.
"""

THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP = 4, 8, 12, 16, 20
THUMB_IP, INDEX_PIP, MIDDLE_PIP, RING_PIP, PINKY_PIP = 3, 6, 10, 14, 18
INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP = 5, 9, 13, 17
WRIST = 0


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def palm_scale(lms):
    """Reference length invariant to depth: wrist -> middle MCP."""
    return max(1e-4, dist(lms[WRIST], lms[MIDDLE_MCP]))


def track_point(lms):
    """Cursor anchor: the index fingertip — the point the user aims with."""
    return (lms[INDEX_TIP][0], lms[INDEX_TIP][1])


def pos_ago(hist, now, seconds, fallback):
    """Oldest position in `hist` (oldest -> newest (t, x, y)) no older than
    `seconds` — the click-lookback helper. Falls back when history is empty."""
    for ts, x, y in hist:
        if now - ts <= seconds:
            return x, y
    return fallback


def palm_center(lms):
    """Pose-independent hand anchor (wrist + MCP knuckle average), used to
    match the tracked hand frame-to-frame. Stays put when fingers curl."""
    xs = (lms[WRIST][0] + lms[INDEX_MCP][0] + lms[MIDDLE_MCP][0]
          + lms[RING_MCP][0] + lms[PINKY_MCP][0]) / 5.0
    ys = (lms[WRIST][1] + lms[INDEX_MCP][1] + lms[MIDDLE_MCP][1]
          + lms[RING_MCP][1] + lms[PINKY_MCP][1]) / 5.0
    return (xs, ys)


PRIMARY_MATCH_RADIUS = 0.28   # a hand must be this close (normalized units) to stay "the same hand"
PRIMARY_GRACE_S = 0.7         # how long the primary slot survives without a match


class PrimaryHandSelector:
    """Keeps control on ONE hand: the first that appears, until it is really gone.

    People/hands popping into frame must never steal the cursor. Each frame the
    engine feeds every detected hand's anchor; the selector returns the index of
    the hand that is "the same one" as before (nearest within MATCH_RADIUS of the
    last known position). Other hands are ignored while that match exists.

    If the tracked hand vanishes (left frame, occluded, briefly dropped by the
    detector), the slot is HELD for GRACE_S — a reappearing hand near the last
    position resumes control seamlessly, and a different hand appearing during
    that window does NOT take over. Only after the grace expires does the slot
    free up, and then the next hand present is adopted ("first appearance").
    """

    def __init__(self, match_radius=PRIMARY_MATCH_RADIUS, grace=PRIMARY_GRACE_S):
        self.match_radius = match_radius
        self.grace = grace
        self.anchor = None       # last matched anchor (normalized x, y)
        self.last_seen = None    # wall time of last successful match

    def reset(self):
        self.anchor = None
        self.last_seen = None

    def select(self, anchors, now):
        """anchors: list of (x, y) palm centers, one per detected hand.
        Returns the index of the primary hand or None (slot empty / in grace)."""
        if not anchors:
            return None
        if self.anchor is None or (self.last_seen is not None
                                   and now - self.last_seen > self.grace):
            # fresh acquisition: the first hand that appears takes the slot
            self.anchor = anchors[0]
            self.last_seen = now
            return 0
        best_i, best_d = None, self.match_radius
        for i, (x, y) in enumerate(anchors):
            d = ((x - self.anchor[0]) ** 2 + (y - self.anchor[1]) ** 2) ** 0.5
            if d <= best_d:
                best_i, best_d = i, d
        if best_i is not None:
            self.anchor = anchors[best_i]
            self.last_seen = now
        return best_i


def disambiguate_pinches(l_ratio, r_ratio, threshold, margin=0.15):
    """One thumb serves both click pinches — decide which finger is pinching.

    Returns (left_feed, right_feed): the raw ratio for the clearly-pinching
    finger, 1.0 for the other. When both are below threshold and nearly equal
    (thumb between the two fingers), neither fires — ambiguous frames must not
    click. When neither is below threshold both pass through unchanged.
    """
    l_hit = l_ratio < threshold
    r_hit = r_ratio < threshold
    if l_hit and r_hit:
        lo, hi = (l_ratio, r_ratio) if l_ratio <= r_ratio else (r_ratio, l_ratio)
        if lo > hi * (1 - margin):  # too close to call
            return 1.0, 1.0
        return (l_ratio, 1.0) if l_ratio <= r_ratio else (1.0, r_ratio)
    if l_hit:
        return l_ratio, 1.0
    if r_hit:
        return 1.0, r_ratio
    return l_ratio, r_ratio


class Pinch:
    """Hysteresis + debounce pinch detector for one thumb-finger pair.

    ratio = dist(thumb_tip, finger_tip) / palm_scale
    enter when ratio < threshold; leave when ratio > threshold * 1.55.
    """

    def __init__(self, threshold, sustain=0.09):
        self.threshold = threshold
        self.sustain = sustain  # must be pinched this long before 'enter' fires
        self.held = False
        self.since = 0.0

    def update(self, ratio, now):
        """Returns (entered, left, held) transitions after sustain filtering."""
        if not self.held:
            if ratio < self.threshold:
                if self.since == 0.0:
                    self.since = now
                if now - self.since >= self.sustain:
                    self.held = True
                    return True, False, True
            else:
                self.since = 0.0
        else:
            if ratio > self.threshold * 1.55:
                self.held = False
                self.since = 0.0
                return False, True, False
        return False, False, self.held

    def reset(self):
        self.held = False
        self.since = 0.0


RCLICK_COOLDOWN = 0.4  # minimum gap between right clicks


class ClickGesture:
    """Wraps pinches into mouse-click semantics.

    LEFT (thumb+middle): raw mouse semantics — button down on pinch-enter, up
    on pinch-exit. A quick pinch reads as a click; holding + moving is a drag.
    RIGHT (thumb+ring): discrete — fires once per pinch, after a short confirm
    delay to filter noisy detections, never more often than `right_cooldown`.
    """

    def __init__(self, threshold, right_confirm=0.09, right_cooldown=RCLICK_COOLDOWN):
        self.pinch = Pinch(threshold)
        self.right_confirm = right_confirm
        self.right_cooldown = right_cooldown
        self.left_down = False
        self.right_held = False      # raw ring-pinch state (freezes the cursor)
        self.right_fired = False
        self.right_since = 0.0
        self.last_right = -1e9

    def update_left(self, ratio, now):
        entered, left, _ = self.pinch.update(ratio, now)
        events = []
        if entered and not self.left_down:
            self.left_down = True
            events.append("left_down")
        elif left and self.left_down:
            self.left_down = False
            events.append("left_up")
        return events

    def update_right(self, ratio, now):
        """Independent pinch for thumb+ring. Fires one right click per pinch."""
        if ratio < self.pinch.threshold:
            self.right_held = True
            if self.right_since == 0.0:
                self.right_since = now
            elif (not self.right_fired and now - self.right_since >= self.right_confirm
                  and now - self.last_right >= self.right_cooldown):
                self.right_fired = True
                self.last_right = now
                return ["right_click"]
        else:
            self.right_since = 0.0
            self.right_fired = False
            self.right_held = False
        return []

    def reset(self):
        self.pinch.reset()
        self.left_down = False
        self.right_held = False
        self.right_fired = False
        self.right_since = 0.0


def fingers_extended(lms):
    """(thumb, index, middle, ring, pinky) extended flags, rotation-tolerant."""
    out = []
    ref = palm_scale(lms)

    # thumb: tip-farther-from-index-mcp than IP is
    out.append(dist(lms[THUMB_TIP], lms[INDEX_MCP]) > dist(lms[THUMB_IP], lms[INDEX_MCP]) + 0.015 * ref)
    for tip, pip in ((INDEX_TIP, INDEX_PIP), (MIDDLE_TIP, MIDDLE_PIP),
                     (RING_TIP, RING_PIP), (PINKY_TIP, PINKY_PIP)):
        # tip vs pip: farther from wrist == extended (works upside-down too)
        out.append(dist(lms[tip], lms[WRIST]) > dist(lms[pip], lms[WRIST]) + 0.06 * ref)
    return tuple(out)


def classify_pose(lms, pinching=False):
    """point | scroll | idle — coarse hand pose for mode gating (4200 scheme).

    point:  index extended (others curled) -> cursor follows the index tip;
            both click pinches happen from this pose.
    scroll: index + middle extended, ring + pinky curled (peace sign) ->
            vertical hand motion scrolls; the cursor stays frozen.
    idle:   everything else — open palm, fist, pinky out — cursor frozen.
            A pinky sticking out always reads as "not a control pose", so a
            relaxed half-open hand never moves the cursor by accident.

    `pinching` (thumb close to middle/ring) forces "point": a pinch in progress
    must never be mistaken for the peace-sign scroll pose even though the
    middle finger is half-extended while it is pinching.
    """
    _, i, m, r, p = fingers_extended(lms)
    if p or not i:
        return "idle"
    if pinching:
        return "point"
    if m and not r:
        return "scroll"
    if m and r:
        return "idle"
    return "point"


class ScrollAccumulator:
    """Peace-sign scroll: consume hand y-delta, emit wheel notches.

    Deltas below `deadzone` are discarded, so micro-jitter never accumulates
    into a scroll (the prototype's SCROLL_DEADZONE_PX idea).
    """

    def __init__(self, pixels_per_notch=0.028, deadzone=0.003):
        self.acc = 0.0
        self.pixels_per_notch = pixels_per_notch
        self.deadzone = deadzone
        self.last_y = None

    def update(self, y, active, speed=1.0, invert=False):
        if not active:
            self.last_y = None
            self.acc = 0.0
            return 0
        if self.last_y is None:
            self.last_y = y
            return 0
        dy = y - self.last_y
        self.last_y = y
        if abs(dy) < self.deadzone:
            return 0
        self.acc += dy * speed
        notches = 0
        while abs(self.acc) >= self.pixels_per_notch - 1e-9:
            notches += 1 if self.acc > 0 else -1
            self.acc -= self.pixels_per_notch if self.acc > 0 else -self.pixels_per_notch
        if invert:
            notches = -notches
        return int(notches)


class TravelMapper:
    """Maps a calibrated camera box around a slowly-tracking center to the full screen.

    The box width shrinks as sensitivity rises, so less hand travel moves the
    cursor further. The center follows the hand slowly, so users can drift and
    re-center without re-aiming.
    """

    def __init__(self, sensitivity=0.6, recenter_tau=5.0):
        self.sensitivity = sensitivity
        self.recenter_tau = recenter_tau
        self.center = None

    @property
    def span(self):
        return 0.92 - 0.58 * min(1.0, max(0.1, self.sensitivity))

    def update_center(self, x, y, dt):
        if self.center is None:
            self.center = [x, y]
            return
        k = 1.0 - 2.718281828 ** (-dt / self.recenter_tau)
        self.center[0] += (x - self.center[0]) * k
        self.center[1] += (y - self.center[1]) * k

    def to_screen(self, x, y, screen_w, screen_h):
        span = self.span
        cx, cy = self.center if self.center else (0.5, 0.5)
        nx = (x - (cx - span / 2)) / span
        ny = (y - (cy - span / 2)) / span
        nx = 0.0 if nx < 0 else (1.0 if nx > 1 else nx)
        ny = 0.0 if ny < 0 else (1.0 if ny > 1 else ny)
        return nx * (screen_w - 1), ny * (screen_h - 1)
