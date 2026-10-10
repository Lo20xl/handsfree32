@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\camo_timeline_probe.py > C:\Users\tangy\Desktop\HandJob3000\build\camo_timeline_out.txt 2>&1
echo CAMO_TL_EXIT=%ERRORLEVEL% >> C:\Users\tangy\Desktop\HandJob3000\build\camo_timeline_out.txt
