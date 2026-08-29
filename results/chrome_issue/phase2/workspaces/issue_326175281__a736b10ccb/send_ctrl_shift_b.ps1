# Native SendInput: bring Chrome window to foreground, send Ctrl+Shift+B (show bookmark bar)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
}
"@
$proc = Get-Process chrome | Where-Object { $_.MainWindowTitle -match 'Logged-in Service' } | Select-Object -First 1
if (-not $proc) { Write-Output 'CHROME_WINDOW_NOT_FOUND'; exit 1 }
Write-Output ('WINDOW_TITLE: ' + $proc.MainWindowTitle)
[Win32]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 800
# Ctrl+Shift+B
[Win32]::keybd_event(0x11, 0, 0, [UIntPtr]::Zero)   # Ctrl down
[Win32]::keybd_event(0x10, 0, 0, [UIntPtr]::Zero)   # Shift down
[Win32]::keybd_event(0x42, 0, 0, [UIntPtr]::Zero)   # B down
[Win32]::keybd_event(0x42, 0, 2, [UIntPtr]::Zero)   # B up
[Win32]::keybd_event(0x10, 0, 2, [UIntPtr]::Zero)   # Shift up
[Win32]::keybd_event(0x11, 0, 2, [UIntPtr]::Zero)   # Ctrl up
Write-Output 'SENT_CTRL_SHIFT_B'
