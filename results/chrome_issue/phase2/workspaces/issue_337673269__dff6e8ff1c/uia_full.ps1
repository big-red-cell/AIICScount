# Full unfiltered UIA dump of Chrome main window
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$chromePid = [int]$args[0]
$root = [System.Windows.Automation.AutomationElement]::RootElement
$condPid = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $chromePid)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $condPid)
if (-not $win) { Write-Output "NO WINDOW FOUND"; exit 1 }
$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
Write-Output ("COUNT: " + $all.Count)
foreach ($el in $all) {
  $ct = $el.Current.ControlType.ProgrammaticName -replace 'ControlType\.',''
  $name = $el.Current.Name
  $val = ""
  try { $val = $el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value } catch {}
  $aid = $el.Current.AutomationId
  Write-Output ("[{0}] id='{1}' name='{2}' value='{3}'" -f $ct, $aid, $name, $val)
}
