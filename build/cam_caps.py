"""Camera capability probe: what modes do the cameras on THIS machine really deliver?
Run from repo root: .venv/Scripts/python.exe build/cam_caps.py
"""
import time

import cv2
import numpy as np

FRAME = cv2.VideoWriter_fourcc(*"MJPG")


def measure(cap, n=25):
    ts = []
    ok_n = 0
    last = None
    for _ in range(n):
        t0 = time.perf_counter()
        ok, fr = cap.read()
        dt = time.perf_counter() - t0
        if ok and fr is not None:
            ok_n += 1
            if last is not None:
                ts.append(time.perf_counter() - last)
            last = time.perf_counter()
    if not ts:
        return ok_n, None, None, None
    med = float(np.median(ts))
    return ok_n, med, 1.0 / med if med else None, fr.shape if ok else None


for idx in range(4):
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap.release()
        print(f"cam {idx}: closed (DSHOW)")
        continue
    ok, fr = cap.read()
    print(f"cam {idx}: open, first read ok={ok} shape={None if fr is None else fr.shape}")
    for (w, h, fps, mjpg) in ((854, 480, 30, False), (854, 480, 60, True), (1280, 720, 60, True),
                              (1280, 720, 30, False), (1920, 1080, 30, True), (640, 480, 60, True)):
        if mjpg:
            cap.set(cv2.CAP_PROP_FOURCC, FRAME)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        cap.set(cv2.CAP_PROP_FPS, fps)
        got_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        got_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        got_f = cap.get(cv2.CAP_PROP_FPS)
        ok_n, med, real_fps, shape = measure(cap)
        tag = "MJPG" if mjpg else "----"
        print(f"  req {w}x{h}@{fps} {tag} -> got {got_w:.0f}x{got_h:.0f}@{got_f:.0f} | "
              f"{ok_n}/25 ok, real {real_fps:.1f} fps" if real_fps else f"  req {w}x{h}@{fps} {tag} -> FAIL")
    cap.release()
print("CAM_CAPS_DONE")
