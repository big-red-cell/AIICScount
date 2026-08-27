# Click the omnibox star button via UIA, then dump the tree to a UTF-8 file.
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$chromePid = [int]$args[0]
$outFile = $args[1]
$root = [System.Windows.Automation.AutomationElement]::RootElement
$condPid = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $chromePid)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $condPid)
if (-not $win) { Write-Output "NO WINDOW"; exit 1 }

# Find the star button: it's the button whose name contains bookmark-ish text; fallback automation id view_1017
$star = $null
$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
foreach ($el in $all) {
  if ($el.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and $el.Current.AutomationId -eq 'view_1017') { $star = $el; break }
}
if (-not $star) {
  # fallback: button with name matching bookmark
  foreach ($el in $all) {
    if ($el.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and $el.Current.Name -match '书签|Bookmark') { $star = $el; break }
  }
}
if (-not $star) { Write-Output "STAR BUTTON NOT FOUND"; exit 2 }

try {
  $invoke = $star.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
  $invoke.Invoke()
  Write-Output "STAR CLICKED: name='$($star.Current.Name)'"
} catch {
  Write-Output "STAR INVOKE FAILED: $($_.Exception.Message)"
  exit 3
}

Start-Sleep -Seconds 2

# Dump full tree to file
$lines = New-Object System.Collections.Generic.List[string]
$all2 = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$lines.Add("COUNT: $($all2.Count)")
foreach ($el in $all2) {
  $ct = $el.Current.ControlType.ProgrammaticName -replace 'ControlType\.',''
  $name = $el.Current.Name
  $val = ""
  try { $val = $el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value } catch {}
  $aid = $el.Current.AutomationId
  $lines.Add("[{0}] id='{1}' name='{2}' value='{3}'" -f $ct, $aid, $name, $val)
}
[System.IO.File]::WriteAllLines($outFile, $lines, (New-Object System.Text.UTF8Encoding($true)))
Write-Output "TREE DUMPED to $outFile"
