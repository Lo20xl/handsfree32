import cv2, time, numpy as np
for idx in range(3):
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"cam {idx}: closed"); cap.release(); continue
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 854); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    times = []; ok_n = 0
    for i in range(40):
        t0 = time.perf_counter(); ok, fr = cap.read(); dt = time.perf_counter() - t0
        if ok: ok_n += 1; times.append(dt)
    if times:
        med = sorted(times)[len(times)//2]*1000
        print(f"cam {idx}: {ok_n}/40 ok  median {med:.1f}ms  -> {1000/med:.1f} fps  shape {fr.shape if fr is not None else None}")
    else:
        print(f"cam {idx}: 0/40 ok")
    cap.release()
print("DONE")
