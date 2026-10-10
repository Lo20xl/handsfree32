@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\matrix_test.py > build\matrix_out.txt 2>&1
echo MATRIX_EXIT=%ERRORLEVEL% >> build\matrix_out.txt
