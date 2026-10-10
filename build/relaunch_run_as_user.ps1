<#
Relaunch the app in the user's session and re-screenshot (after fixes).
#>
param(
  [string]$User = "LEBIGYAHU1\tangy",
  [string]$Cmd  = "C:\Users\tangy\Desktop\HandJob3000\build\relaunch_ui.cmd",
  [string]$TaskName = 'HandJobUiRelaunch',
  [int]$TimeoutSeconds = 300
)
$out = "C:\Users\tangy\Desktop\HandJob3000\build\relaunch_out.txt"
Remove-Item $out -ErrorAction SilentlyContinue
Remove-Item "C:\Users\tangy\Desktop\HandJob3000\build\ui_screenshot2.png" -ErrorAction SilentlyContinue

schtasks /Create /TN $TaskName /TR "cmd /c $Cmd > $out 2>&1" /SC ONCE /ST 23:59 /RU $User /IT /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 5
  if ((Test-Path $out) -and ((Get-Content $out -Raw -ErrorAction SilentlyContinue) -match 'UI_RELAUNCH_DONE')) { break }
}
Write-Output "OUTPUT:"
if (Test-Path $out) { Write-Output (Get-Content $out -Raw) }
Write-Output ("SCREENSHOT: " + (Test-Path "C:\Users\tangy\Desktop\HandJob3000\build\ui_screenshot2.png"))
schtasks /Delete /TN $TaskName /F | Out-Null
