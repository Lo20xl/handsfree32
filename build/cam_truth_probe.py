"""Ground truth on what camera 0 actually delivers.

Reads ~150 consecutive frames and measures, per consecutive pair:
  - the APP's duplicate metric (16x16 mean-subtracted gray sig, mean|diff|)
  - a full-resolution downscaled pixel mean|diff| (4x smaller, INTER_AREA)
  - exact bit-identity
Saves frame samples as PNGs so the feed can be SEEN, not just measured.

Writes build/cam_truth_out.txt. Run as the logged-in user.
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
        OUT.append("CAM_TRUTH_FAIL no camera")
        return finish()
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    t0 = time.time()
    frames = []
    n_target = 150
    while len(frames) < n_target and time.time() - t0 < 8:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    span = max(1e-6, time.time() - t0)
    if len(frames) < 10:
        OUT.append(f"CAM_TRUTH_FAIL only {len(frames)} frames in {span:.1f}s")
        return finish()

    def sig(frame):
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        s = cv2.resize(g, (16, 16), interpolation=cv2.INTER_AREA).astype(np.int16)
        return s - int(s.mean())

    def small(frame):
        s = cv2.resize(frame, (frame.shape[1] // 4, frame.shape[0] // 4),
                       interpolation=cv2.INTER_AREA).astype(np.int16)
        return s

    sig_diffs, px_diffs, exact = [], [], 0
    prev_sig = None
    prev_sm = None
    for f in frames:
        s = sig(f)
        sm = small(f)
        if prev_sig is not None:
            sig_diffs.append(float(np.abs(s - prev_sig).mean()))
            px_diffs.append(float(np.abs(sm - prev_sm).mean()))
            if np.array_equal(sm, prev_sm):
                exact += 1
        prev_sig, prev_sm = s, sm
    sd = np.array(sig_diffs)
    pd = np.array(px_diffs)
    OUT.append(f"frames={len(frames)} in {span:.2f}s = {len(frames)/span:.1f} reads/s  size={frames[0].shape[1]}x{frames[0].shape[0]}")
    OUT.append(f"APP sig diff (16x16):  p10={np.percentile(sd,10):.3f} p50={np.percentile(sd,50):.3f} "
               f"p90={np.percentile(sd,90):.3f} max={sd.max():.3f}")
    OUT.append(f"  >0.35 (app says 'new'): {(sd>0.35).sum()} of {len(sd)}  = {(sd>0.35).sum()/span:.1f}/s")
    OUT.append(f"PIXEL diff (1/4 res):   p10={np.percentile(pd,10):.3f} p50={np.percentile(pd,50):.3f} "
               f"p90={np.percentile(pd,90):.3f} max={pd.max():.3f}")
    OUT.append(f"  >=1.0 (clearly live):  {(pd>=1.0).sum()} of {len(pd)}  = {(pd>=1.0).sum()/span:.1f}/s")
    OUT.append(f"  <0.05 (essentially same): {(pd<0.05).sum()} of {len(pd)}")
    OUT.append(f"exact bit-identical pairs: {exact} of {len(sd)}")
    for tag, idx in (("start", 0), ("mid", len(frames)//2), ("end", len(frames)-1)):
        p = os.path.join("build", f"cam_truth_{tag}.png")
        cv2.imwrite(p, frames[idx])
        OUT.append(f"saved {p}")
    return finish()


def finish():
    OUT.append("CAM_TRUTH_DONE")
    print("\n".join(OUT))
    sys.stdout.flush()
    os._exit(0)


th = threading.Thread(target=work, daemon=True)
th.start()
th.join(25)
print("\n".join(OUT))
print("CAM_TRUTH_TIMEOUT")
os._exit(2)
