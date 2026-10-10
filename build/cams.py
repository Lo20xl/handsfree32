import cv2
import numpy as np

res = []
for i in range(5):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if cap.isOpened():
        ok, fr = cap.read()
        m = None if fr is None else [int(x) for x in np.mean(fr, axis=(0, 1))]
        res.append((i, "OPEN", ok, m))
    else:
        res.append((i, "closed", None, None))
    cap.release()
print("CAMERAS:", res)

# also try the default MSMF backend for index 0
cap = cv2.VideoCapture(0)
if cap.isOpened():
    ok, fr = cap.read()
    m = None if fr is None else [int(x) for x in np.mean(fr, axis=(0, 1))]
    print("MSMF0:", ok, m)
cap.release()
print("CAMS_DONE")
