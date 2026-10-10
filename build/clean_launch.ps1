$ErrorActionPreference = 'SilentlyContinue'
Write-Output "== kill all =="
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*handjob.main*' } | ForEach-Object {
  Write-Output ("KILL " + $_.ProcessId)
  Stop-Process -Id $_.ProcessId -Force
}
Start-Sleep -Seconds 7
Write-Output ("REMAINING " + (@(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*handjob.main*' }).Count))

Write-Output "== launch =="
schtasks /Create /TN HandJobLaunchOnly /TR "cmd /c C:\Users\tangy\Desktop\HandJob3000\build\launch_only.cmd > C:\Users\tangy\Desktop\HandJob3000\build\launch_out.txt 2>&1" /SC ONCE /ST 23:59 /RU LEBIGYAHU1\tangy /IT /F | Out-Null
schtasks /Run /TN HandJobLaunchOnly | Out-Null
Start-Sleep -Seconds 8
Write-Output ("ALIVE " + (@(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*handjob.main*' }).Count))

Write-Output "== screenshot (as user, ~35s in) =="
schtasks /Create /TN HandJobShoot3 /TR "cmd /c C:\Users\tangy\Desktop\HandJob3000\build\shoot_only.cmd" /SC ONCE /ST 23:59 /RU LEBIGYAHU1\tangy /IT /F | Out-Null
schtasks /Run /TN HandJobShoot3 | Out-Null
Start-Sleep -Seconds 55
Write-Output ("SHOT3 " + (Test-Path "C:\Users\tangy\Desktop\HandJob3000\build\ui_screenshot3.png"))

schtasks /Delete /TN HandJobLaunchOnly /F | Out-Null
schtasks /Delete /TN HandJobShoot3 /F | Out-Null
Write-Output "ALL_DONE"
