<#
Run overlay diagnosis v2 as the logged-in user.
#>
param(
  [string]$User = "LEBIGYAHU1\tangy",
  [string]$Cmd  = "C:\Users\tangy\Desktop\HandJob3000\build\overlay_diag2.cmd",
  [string]$TaskName = 'HandJobOverlayDiag2',
  [int]$TimeoutSeconds = 120
)
$out = "C:\Users\tangy\Desktop\HandJob3000\build\overlay_diag2_out.txt"
Remove-Item $out -ErrorAction SilentlyContinue
schtasks /Create /TN $TaskName /TR "cmd /c $Cmd" /SC ONCE /ST 23:59 /RU $User /IT /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 3
  if ((Test-Path $out) -and ((Get-Content $out -Raw -ErrorAction SilentlyContinue) -match 'DIAG2_EXIT=')) { break }
}
Write-Output "DIAG2 OUTPUT:"
if (Test-Path $out) { Write-Output (Get-Content $out -Raw) }
schtasks /Delete /TN $TaskName /F | Out-Null
