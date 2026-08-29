param(
  [string]$Action = "keys",
  [string]$Title = "",
  [int]$X1 = 0, [int]$Y1 = 0, [int]$X2 = 0, [int]$Y2 = 0,
  [string]$Out = ""
)
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Threading;
public class UI {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, int dx, int dy, uint dwData, UIntPtr dwExtraInfo);
  [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public InputUnion U; }
  [StructLayout(LayoutKind.Explicit)] public struct InputUnion { [FieldOffset(0)] public KEYBDINPUT ki; [FieldOffset(0)] public MOUSEINPUT mi; }
  [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [DllImport("user32.dll")] public static extern uint SendInput(uint n, INPUT[] ins, int cb);
  public static void Key(ushort vk, bool up) {
    INPUT i = new INPUT(); i.type = 1; i.U.ki = new KEYBDINPUT();
    i.U.ki.wVk = vk; i.U.ki.dwFlags = up ? 0x0002u : 0u;
    SendInput(1, new INPUT[] { i }, Marshal.SizeOf(typeof(INPUT)));
  }
  public static void KeyTap(ushort vk) { Key(vk, false); Key(vk, true); }
  public static void Sleep(int ms) { Thread.Sleep(ms); }
  public static void MouseDown() { mouse_event(0x0002, 0, 0, 0, UIntPtr.Zero); }
  public static void MouseUp() { mouse_event(0x0004, 0, 0, 0, UIntPtr.Zero); }
  public static void MoveTo(int x, int y) { SetCursorPos(x, y); Thread.Sleep(40); }
  public static void Click(int x, int y) { MoveTo(x, y); MouseDown(); Thread.Sleep(60); MouseUp(); }
}
"@

function FocusWindow([string]$pattern) {
  $proc = Get-Process chrome -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -match $pattern } | Select-Object -First 1
  if (-not $proc -or $proc.MainWindowHandle -eq 0) { Write-Output "FOCUS_FAIL pattern=$pattern"; return $false }
  [UI]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
  Start-Sleep -Milliseconds 600
  Write-Output "FOCUSED handle=$($proc.MainWindowHandle) title='$($proc.MainWindowTitle)'"
  return $true
}

switch ($Action) {
  "ctrlt" {
    [UI]::Key(0x11, $false); [UI]::KeyTap(0x54); [UI]::Key(0x11, $true)
    Write-Output "CTRLT_SENT"
  }
  "showbar" {
    [UI]::Key(0x11, $false); [UI]::Key(0x10, $false); [UI]::KeyTap(0x42); [UI]::Key(0x10, $true); [UI]::Key(0x11, $true)
    Write-Output "SHOWBAR_SENT"
  }
  "drag" {
    [UI]::MoveTo($X1, $Y1)
    Start-Sleep -Milliseconds 200
    [UI]::MouseDown()
    Start-Sleep -Milliseconds 200
    $steps = 14
    for ($i = 1; $i -le $steps; $i++) {
      $cx = $X1 + [int](($X2 - $X1) * $i / $steps)
      $cy = $Y1 + [int](($Y2 - $Y1) * $i / $steps)
      [UI]::MoveTo($cx, $cy)
      Start-Sleep -Milliseconds 60
    }
    Start-Sleep -Milliseconds 250
    [UI]::MouseUp()
    Write-Output "DRAG_SENT $X1,$Y1 -> $X2,$Y2"
  }
  "keys" {
    # F6 F6 Right Enter (bookmarks-bar navigation)
    [UI]::KeyTap(0x75); Start-Sleep -Milliseconds 350
    [UI]::KeyTap(0x75); Start-Sleep -Milliseconds 350
    [UI]::KeyTap(0x27); Start-Sleep -Milliseconds 250
    [UI]::KeyTap(0x0D)
    Write-Output "KEYS_SENT"
  }
  "keys2" {
    # F6 F6 Enter
    [UI]::KeyTap(0x75); Start-Sleep -Milliseconds 350
    [UI]::KeyTap(0x75); Start-Sleep -Milliseconds 350
    [UI]::KeyTap(0x0D)
    Write-Output "KEYS2_SENT"
  }
  "keys3" {
    # F6 Enter
    [UI]::KeyTap(0x75); Start-Sleep -Milliseconds 350
    [UI]::KeyTap(0x0D)
    Write-Output "KEYS3_SENT"
  }
  "keys4" {
    # F6 F6 F6 Right Enter
    [UI]::KeyTap(0x75); Start-Sleep -Milliseconds 300
    [UI]::KeyTap(0x75); Start-Sleep -Milliseconds 300
    [UI]::KeyTap(0x75); Start-Sleep -Milliseconds 300
    [UI]::KeyTap(0x27); Start-Sleep -Milliseconds 250
    [UI]::KeyTap(0x0D)
    Write-Output "KEYS4_SENT"
  }
  "click" {
    [UI]::Click($X1, $Y1)
    Write-Output "CLICK_SENT $X1,$Y1"
  }
  "shot" {
    Add-Type -AssemblyName System.Drawing
    $w = $X2; $h = $Y2
    $bmp = New-Object System.Drawing.Bitmap($w, $h)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($X1, $Y1, 0, 0, (New-Object System.Drawing.Size($w, $h)))
    $g.Dispose()
    $bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    Write-Output "SHOT_SAVED $Out"
  }
}
