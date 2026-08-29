param([int]$Hwnd, [int]$Count = 8)
$src = @'
using System;
using System.Runtime.InteropServices;
public class FgWin {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr wp, IntPtr lp);
}
'@
Add-Type $src
$h = [IntPtr]$Hwnd
[void][FgWin]::ShowWindow($h, 9) # SW_RESTORE
# AttachThreadInput trick
$fg = [FgWin]::GetForegroundWindow()
$fgpid = 0; $tgpid = 0
[void][FgWin]::GetWindowThreadProcessId($fg, [ref]$fgpid)
[void][FgWin]::GetWindowThreadProcessId($h, [ref]$tgpid)
$fgThread = [FgWin]::GetWindowThreadProcessId($fg, [ref]$fgpid)
$fgTid = 0
[void][FgWin]::GetWindowThreadProcessId($fg, [ref]$fgpid)
$cur = [FgWin]::GetCurrentThreadId()
$att = [FgWin]::AttachThreadInput($cur, $fgpid, $true)
[void][FgWin]::SetForegroundWindow($h)
Start-Sleep -Milliseconds 300
[void][FgWin]::AttachThreadInput($cur, $fgpid, $false)
$fg2 = [FgWin]::GetForegroundWindow()
Write-Output ("foreground now: {0} (target {1})" -f $fg2, $h)
$wshell = New-Object -ComObject WScript.Shell
for ($i = 0; $i -lt $Count; $i++) {
  $wshell.SendKeys('{ENTER}')
  Start-Sleep -Milliseconds 250
}
Write-Output ("sent {0} ENTER presses" -f $Count)
