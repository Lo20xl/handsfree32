@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\ulw_minimal_test.py > build\ulw_minimal_out.txt 2>&1
echo ULW_EXIT=%ERRORLEVEL% >> build\ulw_minimal_out.txt
