@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\real_cam_engine_check.py > C:\Users\tangy\Desktop\HandJob3000\build\real_cam_out.txt 2>&1
echo REALCAM_EXIT=%ERRORLEVEL% >> C:\Users\tangy\Desktop\HandJob3000\build\real_cam_out.txt
