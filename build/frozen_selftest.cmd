@echo off
rem Run the FROZEN exe selftest in the interactive session (real audio host)
cd /d C:\Users\tangy\Desktop\HandJob3000
echo === FROZEN SELFTEST === > "build\frozen_selftest_out.txt" 2>&1
dist\HandJob3000\HandJob3000.exe --selftest >> "build\frozen_selftest_out.txt" 2>&1
echo SELFTEST_EXIT=%ERRORLEVEL% >> "build\frozen_selftest_out.txt"
