Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*handjob.main*' } | ForEach-Object {
  $line = $_.ProcessId.ToString() + ' | ' + $_.Name + ' | ' + $_.CreationDate.ToString('HH:mm:ss')
  Write-Output $line
}
Write-Output "---"
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*handjob.main*' } | ForEach-Object {
  Write-Output ($_.ProcessId.ToString() + ' CMD: ' + $_.CommandLine)
}
