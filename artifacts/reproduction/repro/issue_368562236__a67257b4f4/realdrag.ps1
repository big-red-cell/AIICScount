# Real OS-level drag-and-drop between two Chrome windows (issue 368562236)
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class Win32 {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);
  [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
  public const uint MOUSEEVENTF_LEFTUP   = 0x0004;
}
"@

$chromePid = (Get-Process chrome -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1).Id
if (-not $chromePid) { $chromePid = (Get-Process chrome -ErrorAction Stop | Select-Object -First 1).Id }
Write-Output "chrome pid: $chromePid"

$windows = @{}
$cb = {
  param($hWnd, $lParam)
  $pid2 = 0
  [Win32]::GetWindowThreadProcessId($hWnd, [ref]$pid2) | Out-Null
  if ($pid2 -eq $chromePid) {
    $sb = New-Object System.Text.StringBuilder 256
    [Win32]::GetWindowText($hWnd, $sb, 256) | Out-Null
    $title = $sb.ToString()
    if ($title -match 'dragme') { $script:windows['A'] = $hWnd }
    if ($title -match 'dropme') { $script:windows['B'] = $hWnd }
  }
  return $true
}
[Win32]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
Write-Output ("windowA={0} windowB={1}" -f $windows['A'], $windows['B'])
if (-not $windows['A'] -or -not $windows['B']) { throw 'windows not found' }

$rects = @{}
foreach ($k in 'A','B') {
  $r = New-Object Win32+RECT
  [Win32]::GetWindowRect($windows[$k], [ref]$r) | Out-Null
  $c = New-Object Win32+RECT
  [Win32]::GetClientRect($windows[$k], [ref]$c) | Out-Null
  $dpi = [Win32]::GetDpiForWindow($windows[$k])
  $rects[$k] = @{ win = @($r.Left, $r.Top, $r.Right, $r.Bottom); client = @($c.Left, $c.Top, $c.Right, $c.Bottom); dpi = $dpi }
  Write-Output ("win{0}: L={1} T={2} R={3} B={4} client=({5},{6},{7},{8}) dpi={9}" -f $k, $r.Left, $r.Top, $r.Right, $r.Bottom, $c.Left, $c.Top, $c.Right, $c.Bottom, $dpi)
}

# element CSS rects (from rects.json)
$j = Get-Content "$PSScriptRoot\rects.json" -Raw | ConvertFrom-Json
$scaleA = $rects['A'].dpi / 96.0
$scaleB = $rects['B'].dpi / 96.0
Write-Output "scaleA=$scaleA scaleB=$scaleB"

function ClientToScreen($win, $cssRect, $scale) {
  $w = $rects[$win].win
  $c = $rects[$win].client
  $frameL = ($w[2] - $w[0] - ($c[2] - $c[0])) / 2
  $frameT = ($w[3] - $w[1] - ($c[3] - $c[1])) - $frameL
  $ox = $w[0] + $frameL
  $oy = $w[1] + $frameT
  $cx = $ox + ($cssRect.left + $cssRect.width / 2) * $scale
  $cy = $oy + ($cssRect.top + $cssRect.height / 2) * $scale
  return @($cx, $cy)
}

$ptA = ClientToScreen 'A' $j.rectA $scaleA
$ptB = ClientToScreen 'B' $j.rectB $scaleB
Write-Output ("screenA=({0},{1}) screenB=({2},{3})" -f [math]::Round($ptA[0]), [math]::Round($ptA[1]), [math]::Round($ptB[0]), [math]::Round($ptB[1]))

# bring A to front and restore
[Win32]::ShowWindow($windows['A'], 9) | Out-Null   # SW_RESTORE
[Win32]::ShowWindow($windows['B'], 9) | Out-Null
[Win32]::SetWindowPos($windows['A'], [IntPtr]::Zero, 0, 0, 540, 640, 0x0010) | Out-Null   # SWP_NOZORDER
[Win32]::SetWindowPos($windows['B'], [IntPtr]::Zero, 700, 0, 540, 640, 0x0010) | Out-Null
Start-Sleep -Milliseconds 800
# re-read rects after positioning and recompute points
foreach ($k in 'A','B') {
  $r = New-Object Win32+RECT
  [Win32]::GetWindowRect($windows[$k], [ref]$r) | Out-Null
  $c = New-Object Win32+RECT
  [Win32]::GetClientRect($windows[$k], [ref]$c) | Out-Null
  $dpi = [Win32]::GetDpiForWindow($windows[$k])
  $rects[$k] = @{ win = @($r.Left, $r.Top, $r.Right, $r.Bottom); client = @($c.Left, $c.Top, $c.Right, $c.Bottom); dpi = $dpi }
  Write-Output ("repos win{0}: L={1} T={2} R={3} B={4} client=({5},{6},{7},{8}) dpi={9}" -f $k, $r.Left, $r.Top, $r.Right, $r.Bottom, $c.Left, $c.Top, $c.Right, $c.Bottom, $dpi)
}
$scaleA = $rects['A'].dpi / 96.0
$scaleB = $rects['B'].dpi / 96.0
$ptA = ClientToScreen 'A' $j.rectA $scaleA
$ptB = ClientToScreen 'B' $j.rectB $scaleB
Write-Output ("recomputed screenA=({0},{1}) screenB=({2},{3})" -f [math]::Round($ptA[0]), [math]::Round($ptA[1]), [math]::Round($ptB[0]), [math]::Round($ptB[1]))
[Win32]::SetForegroundWindow($windows['A']) | Out-Null
Start-Sleep -Milliseconds 400

# real drag: press on #drag in window A, move to #target in window B, release
[Win32]::SetCursorPos([int][math]::Round($ptA[0]), [int][math]::Round($ptA[1])) | Out-Null
Start-Sleep -Milliseconds 300
[Win32]::mouse_event([Win32]::MOUSEEVENTF_LEFTDOWN, 0, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 300
# small nudge to start the drag
[Win32]::SetCursorPos([int][math]::Round($ptA[0]) + 20, [int][math]::Round($ptA[1]) + 8) | Out-Null
Start-Sleep -Milliseconds 300
$steps = 30
for ($i = 1; $i -le $steps; $i++) {
  $x = [math]::Round($ptA[0] + 20 + (($ptB[0] - $ptA[0] - 20) * $i / $steps))
  $y = [math]::Round($ptA[1] + 8 + (($ptB[1] - $ptA[1] - 8) * $i / $steps))
  [Win32]::SetCursorPos([int]$x, [int]$y) | Out-Null
  Start-Sleep -Milliseconds 50
}
Start-Sleep -Milliseconds 500
[Win32]::mouse_event([Win32]::MOUSEEVENTF_LEFTUP, 0, 0, 0, [UIntPtr]::Zero)
Write-Output "DRAG COMPLETE"
Start-Sleep -Seconds 2
Write-Output "DONE"
