"""Multi-stack camera test on camera 0 while Camo Studio is open:
  1) screenshot of the desktop (what Camo Studio shows right now)
  2) OpenCV/DShow (the app's stack): unique rate + brightness
  3) OpenCV/MSMF (alternative backend): unique rate + brightness
  4) saves one frame per stack + the screenshot
Writes build/camo_multi_out.txt. Run as the logged-in user.
"""
import os
import sys
import threading
import time

OUT = []


def work():
    import cv2
    import numpy as np

    # 1) desktop screenshot (Camo Studio state)
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        img.save(os.path.join("build", "desktop_now.png"))
        OUT.append(f"desktop shot saved ({img.size[0]}x{img.size[1]})")
    except Exception as e:
        OUT.append(f"desktop shot failed: {e}")

    def test(tag, backend, n=60, secs=6.0):
        cap = cv2.VideoCapture(0, backend)
        if not cap.isOpened():
            OUT.append(f"{tag}: OPEN FAILED")
            return
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        t0 = time.time()
        frames = []
        while len(frames) < n and time.time() - t0 < secs:
            ok, f = cap.read()
            if not ok:
                break
            frames.append(f)
        span = max(1e-6, time.time() - t0)
        if not frames:
            OUT.append(f"{tag}: no frames")
            return
        def sig(f):
            g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
            s = cv2.resize(g, (16, 16), interpolation=cv2.INTER_AREA).astype(np.int16)
            return s - int(s.mean())
        uniq = exact = 0
        prev = None
        for f in frames:
            s = sig(f)
            if prev is not None:
                d = float(np.abs(s - prev).mean())
                if d > 0.35:
                    uniq += 1
                if d == 0.0:
                    exact += 1
            prev = s
        b = float(frames[-1].mean())
        OUT.append(f"{tag}: {len(frames)} frames in {span:.1f}s = {len(frames)/span:.1f} reads/s, "
                   f"unique={uniq}, exact={exact}, brightness={b:.1f}")
        p = os.path.join("build", f"camo_multi_{tag.split('/')[0]}.png")
        cv2.imwrite(p, frames[-1])

    test("dshow", cv2.CAP_DSHOW)
    test("msmf", cv2.CAP_MSMF)
    OUT.append("CAMO_MULTI_DONE")
    print("\n".join(OUT))
    sys.stdout.flush()
    os._exit(0)


th = threading.Thread(target=work, daemon=True)
th.start()
th.join(40)
print("\n".join(OUT))
print("CAMO_MULTI_TIMEOUT")
os._exit(2)
