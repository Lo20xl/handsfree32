@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\ulw_canonical_test.py > build\ulw_canonical_out.txt 2>&1
echo CANON_EXIT=%ERRORLEVEL% >> build\ulw_canonical_out.txt
