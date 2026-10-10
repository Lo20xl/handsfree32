@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
"dist\HandJob4100\HandJob4100.exe" --probe > "build\probe4100_out.txt" 2>&1
echo PROBE4100_EXIT=%ERRORLEVEL% >> "build\probe4100_out.txt"
