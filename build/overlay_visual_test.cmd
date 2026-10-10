@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
.venv\Scripts\python.exe build\overlay_visual_test.py > build\overlay_visual_out.txt 2>&1
echo VISUAL_EXIT=%ERRORLEVEL% >> build\overlay_visual_out.txt
