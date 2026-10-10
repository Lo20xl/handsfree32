@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\cam_diag.py > C:\Users\tangy\Desktop\HandJob3000\build\cam_diag_out.txt 2>&1
echo CAM_DIAG_EXIT=%ERRORLEVEL% >> C:\Users\tangy\Desktop\HandJob3000\build\cam_diag_out.txt
