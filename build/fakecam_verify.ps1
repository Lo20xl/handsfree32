$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*handjob.main*' } | ForEach-Object {
  Write-Output ("KILL " + $_.ProcessId)
  Stop-Process -Id $_.ProcessId -Force
}
Start-Sleep -Seconds 8
Write-Output ("REMAINING " + (@(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*handjob.main*' }).Count))

# fakecam instance (bypasses the wedged virtual-camera driver)
schtasks /Run /TN HandJobFakeCam | Out-Null
Start-Sleep -Seconds 30

Write-Output "== foreground + shoot =="
Add-Type -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd); [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);' -Name W -Namespace X | Out-Null
$p = Get-Process | Where-Object { $_.MainWindowTitle -like 'HandJob3000*' } | Select-Object -First 1
if ($p) {
  [X.W]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
  [X.W]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
  Write-Output ("FOREGROUND " + $p.Id)
} else { Write-Output "APP WINDOW NOT FOUND" }
Start-Sleep -Seconds 3
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap($b.Width, $b.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
$bmp.Save('C:\Users\tangy\Desktop\HandJob3000\build\ui_screenshot6.png')
Write-Output "SHOT6_SAVED"
