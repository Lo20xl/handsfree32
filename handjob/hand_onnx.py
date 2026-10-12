"""hand_onnx.py — optional ONNX Runtime hand-tracking backend (GPU via DirectML).

Why this exists: the MediaPipe pip build on Windows is CPU-only ("GPU
processing is disabled in build flags"), so the landmark stage costs ~7-10 ms
of CPU per frame. This module reimplements the same MediaPipe hand pipeline on
two ONNX conversions of the official model weights:

    palm_detection_lite/full.onnx   192x192 -> 2016 SSD anchors (raw outputs)
    hand_landmark_lite/full.onnx    224x224 crop -> 21 landmarks + world lms

Through DirectML on a discrete GPU the landmark stage measures ~0.5-0.6 ms and
palm ~0.6 ms (vs 7.5 ms / 2.5 ms CPU); MediaPipe's CPU landmarker measured
~7.5 ms/frame total. The landmark math (adaptive crop from wrist + middle-MCP,
rotation alignment, inverse mapping) follows the MediaPipe hand-landmark
algorithm; numerics are validated against MediaPipe on real frames by
build/onnx_e2e_probe.py.

Interface (deliberately mirrors what engine.py uses from MediaPipe):

    lm = OnnxHandLandmarker(palm_onnx, landmark_onnx, num_hands=1)
    res = lm.detect_for_video(bgr_or_mpimage, timestamp_ms)
    res.hand_landmarks        # [[x, y, z] * 21] normalized image coords
    res.hand_world_landmarks  # [..] or None
    res.handedness, res.score # floats
    lm.close()
"""
from __future__ import annotations

import math
import time

import cv2
import numpy as np
import onnxruntime as ort

# ------------------------------------------------------------------ constants
PALM_SIZE = 192                      # model input side (letterboxed, aspect kept)
SCORE_THRESH = 0.5
DECODE_SCALE = 192.0                 # regressor scale from palm_detection_cpu.pbtxt
CROP_SIDE_SCALE = 2.6                # RectTransformation scale_x/scale_y
CROP_SHIFT_Y = -0.5                  # RectTransformation shift_y
MIN_PALM_SCALE = 0.1484375
MAX_PALM_SCALE = 0.75
RECT_MAX_AGE_S = 0.5            # a smoothed palm rect older than this is dropped
                                # (a detection miss leaves the stale rect in place,
                                # so a hand reappearing near the old spot must not
                                # be EMA'd toward a position from seconds ago)
STRIDES = (8, 16, 16, 16)
ANCHOR_OFFSET = 0.5


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _ssd_anchors(size=PALM_SIZE):
    """BlazePalm SSD anchors (2016 for 192x192, 2 per cell).

    NOTE: with `fixed_anchor_size: true` the C++ SsdAnchorsCalculator sets every
    anchor's w/h to **1.0** (ssd_anchors_calculator.cc: `if fixed_anchor_size:
    new_anchor.set_w(1.0f); set_h(1.0f)`) — decode is relative to unit boxes,
    which is what makes the keypoint deltas ~10x larger than a naive
    scale-sized anchor would."""
    anchors = []
    n_layers = len(STRIDES)
    for i, stride in enumerate(STRIDES):
        fm = size // stride
        for y in range(fm):
            for x in range(fm):
                cx = (x + ANCHOR_OFFSET) / fm
                cy = (y + ANCHOR_OFFSET) / fm
                anchors.append((cx, cy, 1.0, 1.0))
                anchors.append((cx, cy, 1.0, 1.0))
    return np.asarray(anchors, dtype=np.float32)


def _nms_top1(boxes, scores):
    idx = int(np.argmax(scores))
    return idx


def _weighted_nms(boxes, scores, kps, iou_thresh=0.3):
    """MediaPipe's NonMaxSuppressionCalculator with WEIGHTED algorithm:
    walk candidates by score; a box overlapping a kept detection (IoU > thresh)
    is merged into it as a score-weighted average (box + keypoints), otherwise
    it becomes a new detection. Returns kept detections in order (box, score,
    kps), each box (x1, y1, x2, y2)."""
    order = np.argsort(-scores)
    kept = []          # [x1, y1, x2, y2]
    kept_s = []        # combined score
    kept_k = []        # (7, 2)
    for i in order:
        b = boxes[i]
        area = max(1e-9, (b[2] - b[0]) * (b[3] - b[1]))
        absorbed = False
        for j in range(len(kept)):
            k = kept[j]
            x1, y1 = max(b[0], k[0]), max(b[1], k[1])
            x2, y2 = min(b[2], k[2]), min(b[3], k[3])
            iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
            inter = iw * ih
            karea = max(1e-9, (k[2] - k[0]) * (k[3] - k[1]))
            iou = inter / max(1e-9, area + karea - inter)
            if iou > iou_thresh:
                w0, w1 = kept_s[j], scores[i]
                tot = w0 + w1
                kept[j] = (k * w0 + b * w1) / tot
                kept_k[j] = (kept_k[j] * w0 + kps[i] * w1) / tot
                kept_s[j] = tot
                absorbed = True
                break
        if not absorbed:
            kept.append(b.copy())
            kept_s.append(scores[i])
            kept_k.append(kps[i].copy())
    return kept, kept_s, kept_k


class _Pt:
    __slots__ = ("x", "y", "z")

    def __init__(self, x, y, z):
        self.x, self.y, self.z = float(x), float(y), float(z)


class _Result:
    __slots__ = ("hand_landmarks", "hand_world_landmarks", "handedness", "score")

    def __init__(self, hand_landmarks, world, handedness, score):
        self.hand_landmarks = hand_landmarks
        self.hand_world_landmarks = world
        self.handedness = handedness
        self.score = score


class OnnxHandLandmarker:
    """Drop-in-ish replacement for mediapipe's vision.HandLandmarker."""

    def __init__(self, palm_path, landmark_path, num_hands=1, providers=None):
        providers = providers or ["DmlExecutionProvider", "CPUExecutionProvider"]
        so = ort.SessionOptions()
        so.log_severity_level = 3
        self.palm = ort.InferenceSession(palm_path, so, providers=providers)
        self.land = ort.InferenceSession(landmark_path, so, providers=providers)
        self.num_hands = int(num_hands)
        self._anchors = _ssd_anchors()
        self._palm_in = self.palm.get_inputs()[0].name
        self._land_in = self.land.get_inputs()[0].name
        self._last_rect = None        # (cx, cy, side, angle) in image px
        self._last_palm_t = 0.0
        self.stats = {"palm_ms": 0.0, "land_ms": 0.0}

    # ------------------------------------------------------------- palm stage
    def _palm_detect(self, frame_bgr):
        """-> (score, box(cx,cy,w,h px), kp[7,2 px]) in ORIGINAL frame coords.

        Mirrors palm_detection_cpu.pbtxt: letterboxed 192x192 input
        (keep_aspect_ratio, zero border), SSD decode at scale 192 relative to
        unit anchors, weighted NMS (WEIGHTED, IoU .3), then
        DetectionLetterboxRemoval."""
        h, w = frame_bgr.shape[:2]
        s = min(PALM_SIZE / float(w), PALM_SIZE / float(h))
        rw, rh = max(1, int(round(w * s))), max(1, int(round(h * s)))
        pad_x, pad_y = (PALM_SIZE - rw) // 2, (PALM_SIZE - rh) // 2
        resized = cv2.resize(frame_bgr, (rw, rh), interpolation=cv2.INTER_AREA)
        inp_img = np.zeros((PALM_SIZE, PALM_SIZE, 3), np.uint8)
        inp_img[pad_y:pad_y + rh, pad_x:pad_x + rw] = resized
        inp = cv2.cvtColor(inp_img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        inp = np.transpose(inp, (2, 0, 1))[None]         # NCHW
        t0 = time.perf_counter()
        reg, score = self.palm.run(None, {self._palm_in: inp})[:2]
        self.stats["palm_ms"] = (time.perf_counter() - t0) * 1000.0
        reg = reg[0]                                      # [2016, 18]
        score = _sigmoid(score[0, :, 0])                  # [2016]
        keep = np.where(score >= SCORE_THRESH)[0]
        if keep.size == 0:
            return None
        A = self._anchors[keep]
        r = reg[keep]
        scl = DECODE_SCALE
        cx = r[:, 0] / scl * A[:, 2] + A[:, 0]
        cy = r[:, 1] / scl * A[:, 3] + A[:, 1]
        bw = r[:, 2] / scl * A[:, 2]                      # linear size decode
        bh = r[:, 3] / scl * A[:, 3]
        boxes = np.stack([cx - bw / 2.0, cy - bh / 2.0, cx + bw / 2.0, cy + bh / 2.0], axis=1)
        kps = np.zeros((len(keep), 7, 2), np.float32)
        for k in range(7):
            kps[:, k, 0] = r[:, 4 + 2 * k] / scl * A[:, 2] + A[:, 0]
            kps[:, k, 1] = r[:, 5 + 2 * k] / scl * A[:, 3] + A[:, 1]
        kept, kept_s, kept_k = _weighted_nms(boxes, score[keep], kps)
        if not kept:
            return None
        b = kept[0]
        kp = kept_k[0]

        def unlb(nx, ny):
            """letterboxed-normalized -> original image pixels"""
            return (nx * PALM_SIZE - pad_x) / s, (ny * PALM_SIZE - pad_y) / s

        x1, y1 = unlb(float(b[0]), float(b[1]))
        x2, y2 = unlb(float(b[2]), float(b[3]))
        kps_px = np.zeros((7, 2), np.float32)
        for k in range(7):
            kps_px[k, 0], kps_px[k, 1] = unlb(float(kp[k, 0]), float(kp[k, 1]))
        return float(kept_s[0]), ((x1 + x2) / 2.0, (y1 + y2) / 2.0, x2 - x1, y2 - y1), kps_px

    # --------------------------------------------------------- landmark stage
    def _crop(self, frame_bgr, box, kps, rot_sign=1.0, side_scale=None, shift_y=None):
        """MediaPipe palm_detection_detection_to_roi.pbtxt + rect transform:
        rotate so wrist(kp0)->middle-MCP(kp2) is the rect's Y axis (target 90°),
        shift_y -0.5, square_long, scale 2.6 -> 224x224 crop.
        Returns (crop, M) with M mapping ORIGINAL px -> crop px."""
        side_scale = CROP_SIDE_SCALE if side_scale is None else side_scale
        shift_y = CROP_SHIFT_Y if shift_y is None else shift_y
        cx, cy, bw, bh = box
        dx = float(kps[2, 0] - kps[0, 0])
        dy = float(kps[2, 1] - kps[0, 1])
        # C++: rotation = NormalizeRadians(target - atan2(-(y1-y0), x1-x0)), target = pi/2
        rot = math.pi / 2.0 - math.atan2(-dy, dx)
        rot = (rot + math.pi) % (2 * math.pi) - math.pi
        rot *= rot_sign
        # RectTransformation (pixel space): shift (0, -0.5) applied BEFORE squaring
        x_shift = -bh * shift_y * math.sin(rot)
        y_shift = bh * shift_y * math.cos(rot)
        cx2, cy2 = cx + x_shift, cy + y_shift
        side = max(bw, bh) * side_scale
        m = cv2.getRotationMatrix2D((cx2, cy2), math.degrees(rot), 224.0 / side)
        m[0, 2] += 112.0 - cx2
        m[1, 2] += 112.0 - cy2
        crop = cv2.warpAffine(frame_bgr, m, (224, 224), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
        return crop, m

    def _landmark(self, crop_bgr):
        inp = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        inp = np.transpose(inp, (2, 0, 1))[None]
        t0 = time.perf_counter()
        outs = self.land.run(None, {self._land_in: inp})
        self.stats["land_ms"] = (time.perf_counter() - t0) * 1000.0
        return outs

    # ------------------------------------------------------------------ public
    def detect_for_video(self, image, timestamp_ms=None):
        # the engine passes a mediapipe Image wrapping an RGB numpy array;
        # direct callers pass BGR arrays (like cv2.imread output).
        if hasattr(image, "numpy_view"):
            frame = image.numpy_view()
            if frame.ndim == 3 and frame.shape[2] == 3:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        else:
            frame = np.asarray(image)
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        h, w = frame.shape[:2]

        det = self._palm_detect(frame)
        if det is None:
            return _Result([], None, 0.0, 0.0)
        score, box, kps = det
        # keep the box steady across frames (2.5.6) — re-detecting every frame
        # made the landmark crop inherit the detector's pixel-level wander,
        # which reads as whole-cursor jitter.
        #
        # AGE-OUT: a detection miss returns early above WITHOUT touching
        # _last_rect, so a rect from seconds ago stayed the EMA base and a hand
        # reappearing near the old spot was dragged toward a stale position.
        # A rect older than RECT_MAX_AGE_S is dropped instead.
        from .engine import _smooth_box
        if self._last_rect is not None and time.time() - self._last_rect[2] > RECT_MAX_AGE_S:
            self._last_rect = None
        box, kps = _smooth_box(self._last_rect[:2] if self._last_rect else None, box, kps)
        crop, m = self._crop(frame, box, kps)
        outs = self._landmark(crop)
        lm = outs[0][0].astype(np.float64)          # [63] crop-normalized 0..1
        world = outs[3][0].astype(np.float64) if len(outs) > 3 else None
        presence = float(outs[1][0][0]) if len(outs) > 1 else 1.0
        handed = float(outs[2][0][0]) if len(outs) > 2 else 0.0

        # inverse crop map: crop px -> original px
        inv = cv2.invertAffineTransform(m)
        pts = []
        for k in range(21):
            # outputs are [x, y, z] TRIPLES per landmark (63 values) — reading
            # pairs here (stride 2) garbles every landmark after the wrist.
            px = lm[3 * k]
            py = lm[3 * k + 1]
            x = inv[0, 0] * px + inv[0, 1] * py + inv[0, 2]
            y = inv[1, 0] * px + inv[1, 1] * py + inv[1, 2]
            # z: same pixel-ish scale as x/y in the crop; normalize so the
            # stabilizer sees a comparable magnitude across backends.
            z = lm[3 * k + 2] / 224.0
            pts.append(_Pt(x / w, y / h, z))
        self._last_rect = (box, kps, time.time())
        world_lms = None
        if world is not None:
            world_lms = [_Pt(world[3 * k], world[3 * k + 1], world[3 * k + 2]) for k in range(21)]
        return _Result([pts], world_lms, handed, min(float(score), presence))

    def close(self):
        self.palm = None
        self.land = None

    def backend(self):
        try:
            return "+".join(self.land.get_providers())
        except Exception:
            return "closed"
