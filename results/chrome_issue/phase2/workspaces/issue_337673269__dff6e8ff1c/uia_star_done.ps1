Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$chromePid = [int]$args[0]
$outFile = $args[1]
$root = [System.Windows.Automation.AutomationElement]::RootElement
$condPid = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $chromePid)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $condPid)
if (-not $win) { Write-Output "NO WINDOW"; exit 1 }

function Dump-Tree($el, $path) {
  $lines = New-Object System.Collections.Generic.List[string]
  $all = $el.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
  $lines.Add("COUNT: $($all.Count)")
  foreach ($e in $all) {
    $ct = $e.Current.ControlType.ProgrammaticName -replace 'ControlType\.',''
    $name = $e.Current.Name; $val = ""
    try { $val = $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value } catch {}
    $aid = $e.Current.AutomationId
    $lines.Add("[{0}] id='{1}' name='{2}' value='{3}'" -f $ct, $aid, $name, $val)
  }
  [System.IO.File]::WriteAllLines($path, $lines, (New-Object System.Text.UTF8Encoding($true)))
}

# Find star button: automation id view_1017, or name starts with U+4E3A U+6B64 (为此...)
$star = $null
$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
foreach ($el in $all) {
  if ($el.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and $el.Current.AutomationId -eq 'view_1017') { $star = $el; break }
}
if (-not $star) {
  foreach ($el in $all) {
    $n = [string]$el.Current.Name
    if ($el.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and $n.Length -ge 2 -and $n[0] -eq [char]0x4E3A -and $n[1] -eq [char]0x6B64) { $star = $el; break }
  }
}
if (-not $star) { Write-Output "STAR NOT FOUND"; Dump-Tree $win "$outFile"; exit 2 }
$star.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
Write-Output ("STAR_CLICKED name='" + $star.Current.Name + "'")
Start-Sleep -Seconds 2

# Find Done button (U+5B8C U+6210 = 完成) in main window; fallback: any top-level window
$done = $null
$all2 = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
foreach ($el in $all2) {
  $n = [string]$el.Current.Name
  if ($el.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and $n -eq ([string][char]0x5B8C + [char]0x6210)) { $done = $el; break }
}
if ($done) {
  $done.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
  Write-Output "DONE_CLICKED (in window)"
} else {
  # search top-level windows for Done
  $allWins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
  foreach ($w in $allWins) {
    if ($done) { break }
    $wa = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($el in $wa) {
      $n = [string]$el.Current.Name
      if ($el.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and $n -eq ([string][char]0x5B8C + [char]0x6210)) { $done = $el; break }
    }
  }
  if ($done) {
    $done.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    Write-Output "DONE_CLICKED (top-level window)"
  } else {
    Write-Output "DONE_NOT_FOUND"
  }
}
Start-Sleep -Seconds 2
Dump-Tree $win "$outFile"
Write-Output "TREE_DUMPED"
