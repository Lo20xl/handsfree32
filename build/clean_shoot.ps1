$ErrorActionPreference = 'SilentlyContinue'

# close stray consoles from our own task scripts (never touch the user's own cmd/terminal)
Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq 'cmd.exe' -and ($_.CommandLine -match 'launch_only|shoot_only|probe\.cmd|inno_install|relaunch_ui|build_installer')
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Start-Sleep -Seconds 1

# bring HandJob3000 to the foreground
Add-Type -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd); [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);' -Name W -Namespace X | Out-Null
$p = Get-Process | Where-Object { $_.MainWindowTitle -like 'HandJob3000*' } | Select-Object -First 1
if ($p) {
  [X.W]::ShowWindow($p.MainWindowHandle, 9) | Out-Null   # SW_RESTORE
  [X.W]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
  Write-Output ("FOREGROUND " + $p.Id + " " + $p.MainWindowTitle)
} else {
  Write-Output "APP WINDOW NOT FOUND"
}

Start-Sleep -Seconds 2

Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap($b.Width, $b.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
$bmp.Save('C:\Users\tangy\Desktop\HandJob3000\build\ui_screenshot4.png')
Write-Output "SHOT4_SAVED"
