@echo off
rem kill any running HandJob3000 app (dev pythonw running handjob.main)
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*handjob.main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Output ('KILLED ' + $_.ProcessId) }"
timeout /t 6 /nobreak > nul
cd /d C:\Users\tangy\Desktop\HandJob3000
start "" ".venv\Scripts\pythonw.exe" -m handjob.main
timeout /t 22 /nobreak > nul
powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; $b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; $bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height); $g=[System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); $bmp.Save('C:\Users\tangy\Desktop\HandJob3000\build\ui_screenshot2.png'); Write-Output 'SHOT_SAVED'"
echo UI_RELAUNCH_DONE
