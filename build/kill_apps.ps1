$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*handjob.main*' } | ForEach-Object {
  Write-Output ("KILL " + $_.ProcessId)
  Stop-Process -Id $_.ProcessId -Force
}
Start-Sleep -Seconds 5
Write-Output ("REMAINING " + (@(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*handjob.main*' }).Count))
