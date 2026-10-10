@echo off
cd /d C:\Users\tangy\Desktop\HandJob3000
start "" ".venv\Scripts\pythonw.exe" -m handjob.main
timeout /t 18 /nobreak > nul
powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; $b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; $bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height); $g=[System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); $bmp.Save('C:\Users\tangy\Desktop\HandJob3000\build\ui_screenshot.png'); Write-Output 'SHOT_SAVED'"
echo UI_LAUNCH_DONE
