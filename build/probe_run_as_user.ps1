<#
Run the HandJob3000 hardware probe AS THE LOGGED-IN USER (session bridge), so the
camera / SendInput / layered-window paths are exercised in an interactive session.
#>
param(
  [string]$User = "LEBIGYAHU1\tangy",
  [string]$Cmd  = "C:\Users\tangy\Desktop\HandJob3000\build\probe.cmd",
  [string]$TaskName = 'HandJobProbe',
  [int]$TimeoutSeconds = 300
)
$out = "C:\Users\tangy\Desktop\HandJob3000\build\probe_out.txt"
Remove-Item $out -ErrorAction SilentlyContinue
Remove-Item "C:\Users\tangy\Desktop\HandJob3000\build\probe_done.txt" -ErrorAction SilentlyContinue

schtasks /Create /TN $TaskName /TR "cmd /c $Cmd" /SC ONCE /ST 23:59 /RU $User /IT /RL HIGHEST /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 4
  if ((Test-Path $out) -and ((Get-Content $out -Raw -ErrorAction SilentlyContinue) -match 'PROBE_EXIT=')) {
    Write-Output (Get-Content $out -Raw)
    schtasks /Delete /TN $TaskName /F | Out-Null
    return
  }
}
Write-Output "TIMEOUT:"
if (Test-Path $out) { Write-Output (Get-Content $out -Raw) }
schtasks /Delete /TN $TaskName /F | Out-Null
