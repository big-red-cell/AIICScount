$src = @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class WinEnum {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h, EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
}
'@
Add-Type $src

$rows = New-Object System.Collections.ArrayList
$cb = [WinEnum+EnumProc]{
  param($h, $l)
  $sb = New-Object System.Text.StringBuilder 512
  [WinEnum]::GetWindowText($h, $sb, 512) | Out-Null
  $cls = New-Object System.Text.StringBuilder 256
  [WinEnum]::GetClassName($h, $cls, 256) | Out-Null
  $wpid = 0
  [WinEnum]::GetWindowThreadProcessId($h, [ref]$wpid) | Out-Null
  if ([WinEnum]::IsWindowVisible($h)) {
    $t = $sb.ToString()
    if ($t.Trim().Length -gt 0) {
      [void]$rows.Add(("pid={0} hwnd={1} cls={2} title='{3}'" -f $wpid, $h, $cls.ToString(), $t))
    }
  }
  return $true
}
[void][WinEnum]::EnumWindows($cb, [IntPtr]::Zero)
$rows | ForEach-Object { $_ }
Write-Output "--- child windows of chrome tab window ---"
$chromeWin = Get-Process chrome -EA SilentlyContinue | Where-Object { $_.MainWindowTitle -like '*os.html*' } | Select-Object -First 1
if ($chromeWin) {
  $cb2 = [WinEnum+EnumProc]{
    param($h, $l)
    $sb = New-Object System.Text.StringBuilder 512
    [WinEnum]::GetWindowText($h, $sb, 512) | Out-Null
    $cls = New-Object System.Text.StringBuilder 256
    [WinEnum]::GetClassName($h, $cls, 256) | Out-Null
    $t = $sb.ToString()
    if ($t.Trim().Length -gt 0 -or $cls.ToString() -match 'Dialog|Combo|Edit|Button') {
      Write-Output ("child hwnd={0} cls={1} title='{2}'" -f $h, $cls.ToString(), $t)
    }
    return $true
  }
  [void][WinEnum]::EnumChildWindows($chromeWin.MainWindowHandle, $cb2, [IntPtr]::Zero)
}
