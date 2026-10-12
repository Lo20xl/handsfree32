@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe -m handjob.sonar_probe > C:\Users\tangy\Desktop\HandJob3000\build\sonar_probe_out.txt 2>&1
echo SONAR_PROBE_EXIT=%ERRORLEVEL% >> C:\Users\tangy\Desktop\HandJob3000\build\sonar_probe_out.txt
