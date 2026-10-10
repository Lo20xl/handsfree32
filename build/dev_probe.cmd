@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe -m handjob.main --probe > C:\Users\tangy\Desktop\HandJob3000\build\dev_probe_out.txt 2>&1
echo DEV_PROBE_EXIT=%ERRORLEVEL% >> C:\Users\tangy\Desktop\HandJob3000\build\dev_probe_out.txt
