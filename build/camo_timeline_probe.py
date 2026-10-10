"""Timeline probe: watch camera 0 for 45 s and record the per-second unique
rate + save frames at key moments. Answers: does the camera die on its own a
few seconds after a fresh consumer attaches? Writes build/camo_timeline_out.txt.
Run as the logged-in user.
"""
import os
import sys
import threading
import time

OUT = []


def work():
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        OUT.append("CAMO_TL_FAIL no camera/open failed")
        return finish(1)
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass

    def sig(f):
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        s = cv2.resize(g, (16, 16), interpolation=cv2.INTER_AREA).astype(np.int16)
        return s - int(s.mean())

    t0 = time.time()
    prev = None
    reads = 0
    uniq = 0
    exact = 0
    rows = []
    last_bucket = 0
    shot_at = {2: "2s", 15: "15s", 30: "30s", 44: "44s"}
    while time.time() - t0 < 45:
        ok, f = cap.read()
        if not ok:
            rows.append((int(time.time() - t0), reads, uniq, exact, "READ_FAIL"))
            time.sleep(0.5)
            continue
        reads += 1
        s = sig(f)
        if prev is not None:
            d = float(np.abs(s - prev).mean())
            if d > 0.35:
                uniq += 1
            if d == 0.0:
                exact += 1
        prev = s
        el = int(time.time() - t0)
        if el in shot_at:
            cv2.imwrite(os.path.join("build", f"camo_tl_{shot_at.pop(el)}.png"), f)
        if el >= last_bucket + 5:
            rows.append((el, reads, uniq, exact, f"{f.shape[1]}x{f.shape[0]}"))
            last_bucket = el
    OUT.append(f"{'t':>3} {'reads':>6} {'unique':>7} {'exact':>6}  note   (cumulative)")
    for r in rows:
        OUT.append(f"{r[0]:3d} {r[1]:6d} {r[2]:7d} {r[3]:6d}  {r[4]}")
    OUT.append(f"TOTAL {reads} reads, {uniq} unique, {exact} exact-identical pairs in 45s")
    return finish(0)


def finish(code):
    OUT.append("CAMO_TL_DONE")
    print("\n".join(OUT))
    sys.stdout.flush()
    os._exit(code)


th = threading.Thread(target=work, daemon=True)
th.start()
th.join(60)
print("\n".join(OUT))
print("CAMO_TL_TIMEOUT")
os._exit(2)
