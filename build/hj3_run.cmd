@echo off
rem Launch the installed app as the user, let it run, then dump its log so we
rem can see whether the camera actually opens and at what size.
cd /d C:\Users\tangy\Desktop\HandJob3000
echo === HJ3 RUN START === > "build\hj3_run_out.txt" 2>&1
type "%LOCALAPPDATA%\Programs\HandJob3000\handjob.log" >> "build\hj3_run_out.txt" 2>&1
echo === LAUNCHING === >> "build\hj3_run_out.txt" 2>&1
start "" "%LOCALAPPDATA%\Programs\HandJob3000\HandJob3000.exe"
timeout /t 30 /nobreak > nul
echo === LOG AFTER 30s === >> "build\hj3_run_out.txt" 2>&1
type "%LOCALAPPDATA%\Programs\HandJob3000\handjob.log" >> "build\hj3_run_out.txt" 2>&1
echo === KILLING === >> "build\hj3_run_out.txt" 2>&1
taskkill /F /IM HandJob3000.exe >> "build\hj3_run_out.txt" 2>&1
echo HJ3_RUN_DONE >> "build\hj3_run_out.txt"
