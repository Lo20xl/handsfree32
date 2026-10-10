<#
Run the cursor move+read diagnostic as the logged-in user (interactive session).
Isolates: is SendInput working, or is something else moving/holding the cursor?
#>
param(
  [string]$User = "LEBIGYAHU1\tangy",
  [string]$Cmd  = "C:\Users\tangy\Desktop\HandJob3000\build\cursor_diag.cmd",
  [string]$TaskName = 'HandJobCursorDiag',
  [int]$TimeoutSeconds = 90
)
$out = "C:\Users\tangy\Desktop\HandJob3000\build\cursor_diag_out.txt"
Remove-Item $out -ErrorAction SilentlyContinue
schtasks /Create /TN $TaskName /TR "cmd /c $Cmd" /SC ONCE /ST 23:59 /RU $User /IT /F | Out-Null
schtasks /Run /TN $TaskName | Out-Null
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 2
  if ((Test-Path $out) -and ((Get-Content $out -Raw -ErrorAction SilentlyContinue) -match 'DIAG_EXIT=')) { break }
}
Write-Output "CURSOR DIAG OUTPUT:"
if (Test-Path $out) { Write-Output (Get-Content $out -Raw) }
schtasks /Delete /TN $TaskName /F | Out-Null
