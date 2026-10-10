<#
Run the DEV probe (venv python) as the logged-in user — validates the overlay
visibility fix in the real interactive session before the frozen build.
#>
param(
  [string]$User = "LEBIGYAHU1\tangy",
  [string]$Cmd  = "C:\Users\tangy\Desktop\HandJob3000\build\dev_probe.cmd",
  [string]$TaskName = 'HandJobDevProbe',
  [int]$TimeoutSeconds = 180
)
$out = "C:\Users\tangy\Desktop\HandJob3000\build\dev_probe_out.txt"
Remove-Item $out -ErrorAction SilentlyContinue
schtasks /Create /TN $TaskName /TR "cmd /c $Cmd" /SC ONCE /ST 23:59 /RU $User /IT /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 3
  if ((Test-Path $out) -and ((Get-Content $out -Raw -ErrorAction SilentlyContinue) -match 'DEV_PROBE_EXIT=')) { break }
}
Write-Output "DEV PROBE OUTPUT:"
if (Test-Path $out) { Write-Output (Get-Content $out -Raw) }
schtasks /Delete /TN $TaskName /F | Out-Null
