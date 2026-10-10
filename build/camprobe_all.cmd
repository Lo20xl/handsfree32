@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
set LOG=C:\Users\tangy\Desktop\HandJob3000\build\camprobe_all_out.txt
echo START > %LOG%
"dist\HandJob3000\HandJob3000.exe" --camprobe 0 1280 720 60 3 >> %LOG% 2>&1
echo probe0_exit=%ERRORLEVEL% >> %LOG%
"dist\HandJob3000\HandJob3000.exe" --camprobe 1 1280 720 60 3 >> %LOG% 2>&1
echo probe1_exit=%ERRORLEVEL% >> %LOG%
echo CAMPROBE_ALL_DONE >> %LOG%
