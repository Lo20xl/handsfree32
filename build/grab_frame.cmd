@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\grab_frame.py > build\grab_frame_out.txt 2>&1
echo GRAB_DONE=%ERRORLEVEL% >> build\grab_frame_out.txt
