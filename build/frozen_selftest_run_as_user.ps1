<#
Run the FROZEN HandJob3000 selftest as the logged-in user — the agent session
has no audio host (PortAudioError -9999), so the sonar stack check can only be
judged in the real interactive session.
#>
param(
  [string]$User = "LEBIGYAHU1\tangy",
  [string]$Cmd  = "C:\Users\tangy\Desktop\HandJob3000\build\frozen_selftest.cmd",
  [string]$TaskName = 'HandJob3000Selftest',
  [int]$TimeoutSeconds = 240
)
$out = "C:\Users\tangy\Desktop\HandJob3000\build\frozen_selftest_out.txt"
Remove-Item $out -ErrorAction SilentlyContinue
schtasks /Create /TN $TaskName /TR "cmd /c $Cmd" /SC ONCE /ST 23:59 /RU $User /IT /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 4
  if ((Test-Path $out) -and ((Get-Content $out -Raw -ErrorAction SilentlyContinue) -match 'SELFTEST_EXIT=')) { break }
}
Write-Output "FROZEN SELFTEST OUTPUT:"
if (Test-Path $out) { Write-Output (Get-Content $out -Raw) } else { Write-Output "NO OUTPUT FILE" }
schtasks /Delete /TN $TaskName -F | Out-Null
