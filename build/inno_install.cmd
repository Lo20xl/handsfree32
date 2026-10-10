@echo off
"%~dp0innosetup-6.7.3.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="%~dp0inno_install2.log"
echo INNO_INSTALL_EXIT=%ERRORLEVEL% > "%~dp0inno_done2.txt"
