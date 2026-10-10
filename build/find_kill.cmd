@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\tangy\Desktop\HandJob3000\build\find_kill_overlay_run_as_user.ps1" > "C:\Users\tangy\Desktop\HandJob3000\build\find_kill_out.txt" 2>&1
echo FIND_KILL_EXIT=%ERRORLEVEL% >> "C:\Users\tangy\Desktop\HandJob3000\build\find_kill_out.txt"
