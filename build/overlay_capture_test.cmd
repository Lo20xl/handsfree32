@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\overlay_capture_test.py > build\overlay_capture_out.txt 2>&1
echo CAPTURE_EXIT=%ERRORLEVEL% >> build\overlay_capture_out.txt
