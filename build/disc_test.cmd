@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\disc_test.py > build\disc_out.txt 2>&1
echo DISC_EXIT=%ERRORLEVEL% >> build\disc_out.txt
