param(
  [string]$User = "LEBIGYAHU1\tangy",
  [string]$Cmd  = "C:\Users\tangy\Desktop\HandJob3000\build\comet_start.cmd",
  [string]$TaskName = 'CometCDPLaunch',
  [int]$TimeoutSeconds = 120
)
schtasks /Create /TN $TaskName /TR "cmd /c $Cmd" /SC ONCE /ST 23:59 /RU $User /IT /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$ok = $false
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 3
  try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:9333/json/version' -TimeoutSec 2 -UseBasicParsing
    if ($r.StatusCode -eq 200) { $ok = $true; break }
  } catch {}
}
Write-Output ("CDP_LIVE=" + $ok)
if ($ok) {
  $tabs = (Invoke-WebRequest -Uri 'http://127.0.0.1:9333/json/list' -TimeoutSec 4 -UseBasicParsing).Content | ConvertFrom-Json
  $pages = @($tabs | Where-Object { $_.type -eq 'page' })
  Write-Output ("open tabs: " + $pages.Count)
  $pages | ForEach-Object { Write-Output ("  " + $_.url) }
} else {
  $n = (Get-Process comet -ErrorAction SilentlyContinue | Measure-Object).Count
  Write-Output ("comet processes: " + $n)
}
schtasks /Delete /TN $TaskName /F | Out-Null
