@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\overlay_diag3.py > build\overlay_diag3_out.txt 2>&1
echo DIAG3_EXIT=%ERRORLEVEL% >> build\overlay_diag3_out.txt
