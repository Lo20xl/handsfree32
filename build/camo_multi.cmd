@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\camo_multi_probe.py > C:\Users\tangy\Desktop\HandJob3000\build\camo_multi_out.txt 2>&1
echo CAMO_MULTI_EXIT=%ERRORLEVEL% >> C:\Users\tangy\Desktop\HandJob3000\build\camo_multi_out.txt
