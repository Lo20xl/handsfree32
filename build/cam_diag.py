import sys, time, os
os.chdir(r'C:\Users\tangy\Desktop\HandJob3000')
sys.path.insert(0, r'C:\Users\tangy\Desktop\HandJob3000')
import cv2

print("opencv", cv2.__version__)
for idx in [0, 1, 2, 3]:
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"[{idx}] cannot open")
        continue
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 60)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH); h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    claimed = cap.get(cv2.CAP_PROP_FPS)
    t0 = time.perf_counter(); n = 0; uniq = 0; prev = None; ts0 = None; ts1 = None
    while time.perf_counter() - t0 < 2.5:
        ok, f = cap.read()
        if not ok:
            time.sleep(0.005); continue
        n += 1
        m = cap.get(cv2.CAP_PROP_POS_MSEC)
        if ts0 is None: ts0 = m
        ts1 = m
        hh = hash(f[::16, ::16].tobytes())
        if hh != prev: uniq += 1
        prev = hh
    dt = time.perf_counter() - t0
    span = (ts1 - ts0) if ts0 is not None else -1
    print(f"[{idx}] mode={int(w)}x{int(h)} claimed={claimed:.0f} reads={n/dt:.1f}/s unique={uniq/dt:.1f}/s pos_msec_span={span:.0f}ms over {dt:.1f}s")
    cap.release()
print("CAM_DIAG_DONE")
