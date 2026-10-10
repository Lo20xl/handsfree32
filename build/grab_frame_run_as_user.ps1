param([string]$User = "LEBIGYAHU1\tangy", [string]$Cmd = "C:\Users\tangy\Desktop\HandJob3000\build\grab_frame.cmd", [string]$TaskName = 'HandJobGrabFrame', [int]$TimeoutSeconds = 60)
$out = "C:\Users\tangy\Desktop\HandJob3000\build\grab_frame_out.txt"
Remove-Item $out -ErrorAction SilentlyContinue
schtasks /Create /TN $TaskName /TR "cmd /c $Cmd" /SC ONCE /ST 23:59 /RU $User /IT /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) { Start-Sleep -Seconds 2; if ((Test-Path $out) -and ((Get-Content $out -Raw -ErrorAction SilentlyContinue) -match 'GRAB_DONE=')) { break } }
Write-Output (Get-Content $out -Raw -ErrorAction SilentlyContinue)
schtasks /Delete /TN $TaskName /F | Out-Null
