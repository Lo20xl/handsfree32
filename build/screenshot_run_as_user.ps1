<#
Launch the HandJob3000 UI in the user's session and capture a screenshot of it.
#>
param(
  [string]$User = "LEBIGYAHU1\tangy",
  [string]$Cmd  = "C:\Users\tangy\Desktop\HandJob3000\build\launch_ui.cmd",
  [string]$TaskName = 'HandJobUiShoot',
  [int]$TimeoutSeconds = 240
)
$out = "C:\Users\tangy\Desktop\HandJob3000\build\ui_launch_out.txt"
Remove-Item $out -ErrorAction SilentlyContinue
Remove-Item "C:\Users\tangy\Desktop\HandJob3000\build\ui_screenshot.png" -ErrorAction SilentlyContinue

schtasks /Create /TN $TaskName /TR "cmd /c $Cmd > $out 2>&1" /SC ONCE /ST 23:59 /RU $User /IT /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 5
  if ((Test-Path $out) -and ((Get-Content $out -Raw -ErrorAction SilentlyContinue) -match 'UI_LAUNCH_DONE')) { break }
}
Write-Output "LAUNCH OUTPUT:"
if (Test-Path $out) { Write-Output (Get-Content $out -Raw) }
Write-Output "SCREENSHOT EXISTS:"
Write-Output (Test-Path "C:\Users\tangy\Desktop\HandJob3000\build\ui_screenshot.png")
schtasks /Delete /TN $TaskName /F | Out-Null
