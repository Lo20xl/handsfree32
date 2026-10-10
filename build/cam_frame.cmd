@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
".venv\Scripts\python.exe" -c "import cv2; cap=cv2.VideoCapture(0, cv2.CAP_DSHOW); ok,fr=cap.read(); print('READ', ok, None if fr is None else fr.shape); cv2.imwrite(r'build\cam_frame.png', fr) if ok else None; cap.release(); import statistics; import numpy as np; print('MEAN_BGR', None if fr is None else [int(x) for x in np.mean(fr, axis=(0,1))])" > build\cam_frame_out.txt 2>&1
echo CAM_DONE >> build\cam_frame_out.txt
