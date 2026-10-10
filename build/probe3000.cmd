@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
"dist\HandJob3000\HandJob3000.exe" --probe > "build\probe3000_out.txt" 2>&1
echo PROBE3000_EXIT=%ERRORLEVEL% >> "build\probe3000_out.txt"
