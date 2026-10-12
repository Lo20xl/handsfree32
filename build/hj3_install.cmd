@echo off
rem Install HandJob3000 as the logged-in USER (per-user installer lands in
rem %LOCALAPPDATA%, so it must not be launched from a SYSTEM session).
cd /d C:\Users\tangy\Desktop\HandJob3000
echo === HJ3 INSTALL === > "build\hj3_install_out.txt" 2>&1
tasklist /FI "IMAGENAME eq HandJob3000.exe" 2>&1 | find /I "HandJob3000.exe" > nul
if not errorlevel 1 (
  echo WARNING: app still running, killing >> "build\hj3_install_out.txt" 2>&1
  taskkill /F /IM HandJob3000.exe >> "build\hj3_install_out.txt" 2>&1
)
"dist-installer\HandJob3000-Setup-2.5.9.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- >> "build\hj3_install_out.txt" 2>&1
echo HJ3_INSTALL_EXIT=%ERRORLEVEL% >> "build\hj3_install_out.txt"
echo === VERIFY === >> "build\hj3_install_out.txt" 2>&1
if exist "%LOCALAPPDATA%\Programs\HandJob3000\HandJob3000.exe" (
  for %%F in ("%LOCALAPPDATA%\Programs\HandJob3000\HandJob3000.exe") do echo INSTALLED_EXE_MTIME=%%~tF >> "build\hj3_install_out.txt" 2>&1
) else (
  echo INSTALL_FAILED_NO_EXE >> "build\hj3_install_out.txt" 2>&1
)
"%LOCALAPPDATA%\Programs\HandJob3000\HandJob3000.exe" --selftest >> "build\hj3_install_out.txt" 2>&1
echo HJ3_SELFTEST_EXIT=%ERRORLEVEL% >> "build\hj3_install_out.txt"
