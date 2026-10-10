@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
".venv\Scripts\python.exe" -m handjob.main --probe > "build\probe_out.txt" 2>&1
echo PROBE_EXIT=%ERRORLEVEL% >> "build\probe_out.txt"
