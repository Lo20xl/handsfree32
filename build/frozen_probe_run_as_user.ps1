<#
Run the FROZEN HandJob3000.exe --probe as the logged-in user (interactive session).
#>
param(
  [string]$User = "LEBIGYAHU1\tangy",
  [string]$Cmd  = "C:\Users\tangy\Desktop\HandJob3000\build\frozen_probe.cmd",
  [string]$TaskName = 'HandJobFrozenProbe',
  [int]$TimeoutSeconds = 300
)
$out = "C:\Users\tangy\Desktop\HandJob3000\build\frozen_probe_out.txt"
Remove-Item $out -ErrorAction SilentlyContinue
schtasks /Create /TN $TaskName /TR "cmd /c $Cmd" /SC ONCE /ST 23:59 /RU $User /IT /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 5
  if ((Test-Path $out) -and ((Get-Content $out -Raw -ErrorAction SilentlyContinue) -match 'FROZEN_PROBE_EXIT=')) { break }
}
Write-Output "FROZEN PROBE OUTPUT:"
if (Test-Path $out) { Write-Output (Get-Content $out -Raw) }
schtasks /Delete /TN $TaskName /F | Out-Null
