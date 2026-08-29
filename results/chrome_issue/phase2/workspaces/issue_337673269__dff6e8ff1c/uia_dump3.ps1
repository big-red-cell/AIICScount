Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$chromePid = [int]$args[0]
$outFile = $args[1]
$root = [System.Windows.Automation.AutomationElement]::RootElement
$condPid = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $chromePid)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $condPid)
if (-not $win) { Write-Output "NO WINDOW"; exit 1 }
$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine("COUNT: " + $all.Count)
foreach ($el in $all) {
  $ct = $el.Current.ControlType.ProgrammaticName
  $name = [string]$el.Current.Name
  $aid = [string]$el.Current.AutomationId
  $val = ""
  try { $val = [string]$el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value } catch {}
  [void]$sb.Append("[").Append($ct).Append("] id='").Append($aid).Append("' name='").Append($name).Append("' value='").Append($val).AppendLine("'")
}
[System.IO.File]::WriteAllText($outFile, $sb.ToString(), (New-Object System.Text.UTF8Encoding($true)))
Write-Output ("DUMPED " + $all.Count + " elements to " + $outFile)
