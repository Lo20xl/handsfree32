@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\disc2_test.py > build\disc2_out.txt 2>&1
echo DISC2_EXIT=%ERRORLEVEL% >> build\disc2_out.txt
