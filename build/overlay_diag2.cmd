@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\overlay_diag2.py > build\overlay_diag2_out.txt 2>&1
echo DIAG2_EXIT=%ERRORLEVEL% >> build\overlay_diag2_out.txt
