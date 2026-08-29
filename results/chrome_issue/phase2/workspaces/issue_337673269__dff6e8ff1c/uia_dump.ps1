# UI Automation dump: find Chrome's main window and print Edit controls + key fields.
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $pid)
# find window by process id passed as arg
$chromePid = [int]$args[0]
$condPid = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $chromePid)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $condPid)
if (-not $win) { Write-Output "NO WINDOW FOUND for pid $chromePid"; exit 1 }
Write-Output ("WINDOW: " + $win.Current.Name + " | " + $win.Current.ClassName)

$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
Write-Output ("DESCENDANT COUNT: " + $all.Count)
foreach ($el in $all) {
  $ct = $el.Current.ControlType.ProgrammaticName
  if ($ct -match 'Edit|Text|Button|Pane' -and ($el.Current.Name -or $el.Current.HelpText)) {
    $name = $el.Current.Name
    $val = ""
    try {
      $vp = $el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
      $val = $vp.Current.Value
    } catch {}
    if ($name -or $val) { Write-Output ("{0} | NAME='{1}' | VALUE='{2}'" -f $ct, $name, $val) }
  }
}
