"""Hang-proof camera probe: each camera gets a daemon thread with a hard join
timeout; the process force-exits even if a driver blocks read()/open() forever.
Prints one line per camera: index, opened, frames in N s, alive(wedged?).
Run: .venv/Scripts/python.exe build/cam_probe_safe.py
"""
import json
import os
import sys
import threading
import time

import cv2


def probe(idx, secs, out):
    res = {"opened": None, "frames": 0, "err": None}

    def work():
        try:
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            res["opened"] = bool(cap.isOpened())
            if not res["opened"]:
                cap.release()
                return
            t0 = time.time()
            n = 0
            while time.time() - t0 < secs:
                ok, fr = cap.read()
                if not ok:
                    res["err"] = "read failed"
                    break
                n += 1
            res["frames"] = n
            cap.release()
        except Exception as e:
            res["err"] = repr(e)[:140]

    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(secs + 5)
    out.append({"index": idx, "opened": res["opened"], "frames": res["frames"],
                "err": res["err"], "wedged": th.is_alive()})


out = []
for i in (0, 1):
    probe(i, 4.0, out)
print(json.dumps(out, indent=1))
print("SAFE_PROBE_DONE")
sys.stdout.flush()
os._exit(0)
