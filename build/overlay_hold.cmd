@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\overlay_hold.py > build\overlay_hold_out.txt 2>&1
echo HOLD_EXIT=%ERRORLEVEL% >> build\overlay_hold_out.txt
