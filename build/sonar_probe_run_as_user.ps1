<#
Run the sonar tone sweep as the logged-in user — PortAudio cannot initialise in
a service/SYSTEM session, so any real audio check needs the interactive desktop.
#>
param(
  [string]$User = "LEBIGYAHU1\\tangy",
  [string]$Cmd  = "C:\Users\tangy\Desktop\HandJob3000\build\sonar_probe.cmd",
  [string]$TaskName = 'HandJobSonarProbe',
  [int]$TimeoutSeconds = 180
)
$out = "C:\Users\tangy\Desktop\HandJob3000\build\sonar_probe_out.txt"
Remove-Item $out -ErrorAction SilentlyContinue
schtasks /Create /TN $TaskName /TR "cmd /c $Cmd" /SC ONCE /ST 23:59 /RU $User /IT /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 3
  if ((Test-Path $out) -and ((Get-Content $out -Raw -ErrorAction SilentlyContinue) -match 'SONAR_PROBE_EXIT=')) { break }
}
Write-Output "SONAR SWEEP OUTPUT:"
if (Test-Path $out) { Write-Output (Get-Content $out -Raw) }
schtasks /Delete /TN $TaskName /F | Out-Null
