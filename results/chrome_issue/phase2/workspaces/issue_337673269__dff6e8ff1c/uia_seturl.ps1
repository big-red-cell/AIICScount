Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$chromePid = [int]$args[0]
$url = $args[1]
$root = [System.Windows.Automation.AutomationElement]::RootElement
$condPid = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $chromePid)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $condPid)
if (-not $win) { Write-Output "NO WINDOW"; exit 1 }
$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$edit = $null
foreach ($el in $all) {
  if ($el.Current.ControlType.ProgrammaticName -eq 'ControlType.Edit' -and $el.Current.AutomationId -eq 'view_1012') { $edit = $el; break }
}
if (-not $edit) { Write-Output "OMNIBOX EDIT NOT FOUND"; exit 2 }
try {
  $vp = $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
  $vp.SetValue($url)
  Write-Output "OMNIBOX SET: '$url'"
} catch {
  Write-Output "SETVALUE FAILED: $($_.Exception.Message)"
  exit 3
}
