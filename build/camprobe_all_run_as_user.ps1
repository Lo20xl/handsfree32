<#
Run camprobe-all as the logged-in user and print the output.
#>
param(
  [string]$User = "LEBIGYAHU1\tangy",
  [string]$Cmd  = "C:\Users\tangy\Desktop\HandJob3000\build\camprobe_all.cmd",
  [string]$TaskName = 'HandJobCamProbeAll',
  [int]$TimeoutSeconds = 90
)
$out = "C:\Users\tangy\Desktop\HandJob3000\build\camprobe_all_out.txt"
Remove-Item $out -ErrorAction SilentlyContinue
schtasks /Create /TN $TaskName /TR "cmd /c $Cmd" /SC ONCE /ST 23:59 /RU $User /IT /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 2
  if ((Test-Path $out) -and ((Get-Content $out -Raw -ErrorAction SilentlyContinue) -match 'CAMPROBE_ALL_DONE')) { break }
}
Write-Output "CAMPROBE ALL OUTPUT:"
if (Test-Path $out) { Write-Output (Get-Content $out -Raw) }
schtasks /Delete /TN $TaskName /F | Out-Null
