# Dump UIA tree of the Chrome window (names + control types, depth-limited)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$chromeWin = $null
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
foreach ($w in $all) {
  $pid2 = $w.Current.ProcessId
  $proc = Get-Process -Id $pid2 -EA SilentlyContinue
  if ($proc -and $proc.ProcessName -eq 'chrome') {
    Write-Output ('WINDOW: name=' + $w.Current.Name + ' pid=' + $pid2 + ' class=' + $w.Current.ClassName)
  }
}
function Walk($el, $depth) {
  if ($depth -gt 6) { return }
  $children = $el.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
  foreach ($c in $children) {
    $name = $c.Current.Name
    if ($name -or $c.Current.ControlType.ProgrammaticName -match 'Button|ListItem|Link|Menu|ToolBar') {
      Write-Output (('  ' * $depth) + $c.Current.ControlType.ProgrammaticName + ' | ' + $name)
    }
    Walk $c ($depth + 1)
  }
}
# walk the first chrome window found
foreach ($w in $all) {
  $pid2 = $w.Current.ProcessId
  $proc = Get-Process -Id $pid2 -EA SilentlyContinue
  if ($proc -and $proc.ProcessName -eq 'chrome' -and $w.Current.Name -match 'Logged-in Service') {
    Write-Output '--- TREE ---'
    Walk $w 0
    break
  }
}
