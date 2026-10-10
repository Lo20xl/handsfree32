@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
".venv\Scripts\python.exe" "build\cams.py" > "build\cams_out.txt" 2>&1
echo "== processes ==" >> build\cams_out.txt
tasklist | findstr /i "camo" >> build\cams_out.txt 2>&1
echo CAMS_DONE >> build\cams_out.txt
