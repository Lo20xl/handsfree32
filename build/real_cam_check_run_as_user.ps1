param([string]$User = "LEBIGYAHU1\tangy", [string]$Cmd = "C:\Users\tangy\Desktop\HandJob3000\build\real_cam_check.cmd", [string]$TaskName = 'HandJobRealCam', [int]$TimeoutSeconds = 120)
$out = "C:\Users\tangy\Desktop\HandJob3000\build\real_cam_out.txt"
Remove-Item $out -ErrorAction SilentlyContinue
schtasks /Create /TN $TaskName /TR "cmd /c $Cmd" /SC ONCE /ST 23:59 /RU $User /IT /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) { Start-Sleep -Seconds 3; if ((Test-Path $out) -and ((Get-Content $out -Raw -ErrorAction SilentlyContinue) -match 'REALCAM_EXIT=')) { break } }
Write-Output "REAL CAM CHECK:"
if (Test-Path $out) { Write-Output (Get-Content $out -Raw) }
schtasks /Delete /TN $TaskName /F | Out-Null
