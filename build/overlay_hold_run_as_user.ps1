<#
Launch the overlay hold as the logged-in user, wait for ARMED, then leave it running.
#>
param(
  [string]$User = "LEBIGYAHU1\tangy",
  [string]$Cmd  = "C:\Users\tangy\Desktop\HandJob3000\build\overlay_hold.cmd",
  [string]$TaskName = 'HandJobOverlayHold',
  [int]$TimeoutSeconds = 30
)
$state = "C:\Users\tangy\Desktop\HandJob3000\build\overlay_hold_state.txt"
Remove-Item $state -ErrorAction SilentlyContinue
schtasks /Create /TN $TaskName /TR "cmd /c $Cmd" /SC ONCE /ST 23:59 /RU $User /IT /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 2
  if ((Test-Path $state) -and ((Get-Content $state -Raw -ErrorAction SilentlyContinue) -match 'ARMED')) { break }
}
Write-Output "HOLD STATE:"
if (Test-Path $state) { Write-Output (Get-Content $state -Raw) }
