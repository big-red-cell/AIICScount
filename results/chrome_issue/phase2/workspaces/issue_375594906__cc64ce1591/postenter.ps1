param([int]$Hwnd, [int]$Count = 10)
$src = @'
using System;
using System.Runtime.InteropServices;
public class DlgKeys {
  [StructLayout(LayoutKind.Sequential)] public struct GUITHREADINFO {
    public int cbSize; public uint flags;
    public IntPtr hwndActive; public IntPtr hwndFocus;
    public IntPtr hwndCapture; public IntPtr hwndMenuOwner;
    public IntPtr hwndMoveSize; public IntPtr hwndCaret;
    public System.Drawing.Rectangle rcCaret;
  }
  [DllImport("user32.dll")] public static extern bool GetGUIThreadInfo(uint id, ref GUITHREADINFO info);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr wp, IntPtr lp);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, System.Text.StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, System.Text.StringBuilder s, int n);
}
'@
Add-Type -ReferencedAssemblies System.Drawing $src
$h = [IntPtr]$Hwnd
$tid = 0; $pid = 0
[void][DlgKeys]::GetWindowThreadProcessId($h, [ref]$pid)
$t = [System.Diagnostics.Process]::GetProcessById($pid).Threads | Select-Object -First 1
$info = New-Object DlgKeys+GUITHREADINFO
$info.cbSize = [System.Runtime.InteropServices.Marshal]::SizeOf($info)
$ok = [DlgKeys]::GetGUIThreadInfo([uint32]$t.Id, [ref]$info)
Write-Output ("GetGUIThreadInfo={0} focus=0x{1} active=0x{2}" -f $ok, $info.hwndFocus.ToString('X'), $info.hwndActive.ToString('X'))
$focus = $info.hwndFocus
if ($focus -ne [IntPtr]::Zero) {
  $sb = New-Object System.Text.StringBuilder 256
  [void][DlgKeys]::GetClassName($focus, $sb, 256)
  $sb2 = New-Object System.Text.StringBuilder 256
  [void][DlgKeys]::GetWindowText($focus, $sb2, 256)
  Write-Output ("focus cls='{0}' title='{1}'" -f $sb.ToString(), $sb2.ToString())
}
$target = $focus
if ($target -eq [IntPtr]::Zero) { $target = $h }
for ($i = 0; $i -lt $Count; $i++) {
  [void][DlgKeys]::PostMessage($target, 0x100, [IntPtr]13, [IntPtr]1)   # WM_KEYDOWN VK_RETURN
  [void][DlgKeys]::PostMessage($target, 0x101, [IntPtr]13, [IntPtr]1)   # WM_KEYUP
  Start-Sleep -Milliseconds 200
}
Write-Output ("posted {0} ENTER pairs to 0x{1}" -f $Count, $target.ToString('X'))
