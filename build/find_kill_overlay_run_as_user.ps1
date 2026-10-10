$src = @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class WinEnum2 {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lp);
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lp);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  public static string Find(string match) {
    var sb = new StringBuilder();
    EnumWindows(delegate(IntPtr h, IntPtr lp) {
      var t = new StringBuilder(256);
      GetWindowText(h, t, 256);
      string title = t.ToString();
      if (title.Contains(match)) {
        uint pid;
        GetWindowThreadProcessId(h, out pid);
        sb.AppendLine(h + "|" + pid + "|" + IsWindowVisible(h) + "|" + title);
      }
      return true;
    }, IntPtr.Zero);
    return sb.ToString();
  }
}
'@
Add-Type -TypeDefinition $src

$hits = [WinEnum2]::Find('HandJob')
if (-not $hits) { Write-Output "NO_HANDJOB_WINDOWS"; exit 0 }
$hits -split "`n" | Where-Object { $_ } | ForEach-Object {
  $parts = $_ -split '\|'
  $hwnd = $parts[0]; $pid_ = [int]$parts[1]; $vis = $parts[2]; $title = $parts[3]
  $cl = ''
  try { $cl = (Get-CimInstance Win32_Process -Filter "ProcessId=$pid_).CommandLine" -ErrorAction SilentlyContinue) } catch {}
  Write-Output "WINDOW hwnd=$hwnd pid=$pid_ visible=$vis title=$title"
  if ($cl) { Write-Output "  CMD: $cl" }
  # Kill only if command line clearly is our old overlay test script or app build
  if ($cl -and ($cl -match 'HandJob3000\\build' -or $cl -match 'overlay_hold' -or $cl -match 'overlay_visual' -or $cl -match 'dist\\HandJob3500')) {
    try { Stop-Process -Id $pid_ -Force; Write-Output "  KILLED=Y" } catch { Write-Output "  KILLED=N err=$_" }
  } else {
    Write-Output "  KILLED=N (not matched as our test process)"
  }
}
