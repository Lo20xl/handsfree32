@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000\dist\HandJob3000
HandJob3000.exe --probe > C:\Users\tangy\Desktop\HandJob3000\build\frozen_probe_out.txt 2>&1
echo FROZEN_PROBE_EXIT=%ERRORLEVEL% >> C:\Users\tangy\Desktop\HandJob3000\build\frozen_probe_out.txt
