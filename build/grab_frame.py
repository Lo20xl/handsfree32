"""Capture ONE frame from camera 0 as the user (daemon thread, hard exit)."""
import os
import sys
import threading
import time

import cv2

OUT = "build/live_frame.png"


def grab():
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("NO_CAMERA")
        os._exit(1)
    # warm up a few frames for exposure
    for _ in range(5):
        cap.read()
    ok, frame = cap.read()
    if ok:
        cv2.imwrite(OUT, frame)
        print(f"SAVED {frame.shape}")
    else:
        print("READ_FAIL")
    # don't release() — may block on a wedged driver; just exit
    os._exit(0 if ok else 2)


th = threading.Thread(target=grab, daemon=True)
th.start()
th.join(15)
print("TIMEOUT/WEDGED")
sys.stdout.flush()
os._exit(3)
