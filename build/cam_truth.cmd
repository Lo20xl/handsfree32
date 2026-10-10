@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\cam_truth_probe.py > C:\Users\tangy\Desktop\HandJob3000\build\cam_truth_out.txt 2>&1
echo CAM_TRUTH_EXIT=%ERRORLEVEL% >> C:\Users\tangy\Desktop\HandJob3000\build\cam_truth_out.txt
