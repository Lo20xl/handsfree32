<#
Run the Inno Setup silent installer AS THE LOGGED-IN USER (one-shot scheduled task,
session-bridge pattern) so it lands in the user's own profile, not SYSTEM's.
Usage: powershell -NoProfile -ExecutionPolicy Bypass -File inno_run_as_user.ps1
#>
param(
  [string]$User = "$env:COMPUTERNAME\tangy",
  [string]$Cmd  = "C:\Users\tangy\Desktop\HandJob3000\build\inno_install.cmd",
  [string]$TaskName = 'HandJobInnoInstall',
  [int]$TimeoutSeconds = 300
)
$done = "C:\Users\tangy\Desktop\HandJob3000\build\inno_done.txt"
Remove-Item $done -ErrorAction SilentlyContinue

$tr = "cmd /c $Cmd"
schtasks /Create /TN $TaskName /TR $tr /SC ONCE /ST 23:59 /RU $User /IT /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 4
  if (Test-Path $done) {
    Write-Output "DONE FILE:"
    Get-Content $done -Raw
    break
  }
}
if (-not (Test-Path $done)) {
  Write-Output "TIMEOUT waiting for installer"
  schtasks /Query /TN $TaskName /V /FO LIST | Select-String -Pattern "status|result" -CaseSensitive:$false
}
schtasks /Delete /TN $TaskName /F | Out-Null
Write-Output "ISCC-CHECK:"
if (Test-Path "C:\Users\tangy\AppData\Local\Programs\Inno Setup 6\ISCC.exe") { Write-Output "ISCC FOUND" }
else { Write-Output "ISCC MISSING" }
