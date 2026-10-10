<#
Run the FROZEN HandJob3000 probe as the logged-in user — verifies the packaged
exe's overlay visibility + engine loop in the real interactive session.
#>
param(
  [string]$User = "LEBIGYAHU1\tangy",
  [string]$Cmd  = "C:\Users\tangy\Desktop\HandJob3000\build\probe3000.cmd",
  [string]$TaskName = 'HandJob3000Probe',
  [int]$TimeoutSeconds = 240
)
$out = "C:\Users\tangy\Desktop\HandJob3000\build\probe3000_out.txt"
Remove-Item $out -ErrorAction SilentlyContinue
schtasks /Create /TN $TaskName /TR "cmd /c $Cmd" /SC ONCE /ST 23:59 /RU $User /IT /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 4
  if ((Test-Path $out) -and ((Get-Content $out -Raw -ErrorAction SilentlyContinue) -match 'PROBE3000_EXIT=')) { break }
}
Write-Output "FROZEN 3000 PROBE OUTPUT:"
if (Test-Path $out) { Write-Output (Get-Content $out -Raw) }
schtasks /Delete /TN $TaskName /F | Out-Null
