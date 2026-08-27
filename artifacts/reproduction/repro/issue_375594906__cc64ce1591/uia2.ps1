param([int]$Hwnd)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$el = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Hwnd)
if (-not $el) { Write-Output 'NO_ELEMENT'; exit 1 }
Write-Output ("DIALOG Name='{0}' Class='{1}'" -f $el.Current.Name, $el.Current.ClassName)
$all = $el.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
Write-Output ("descendant count: {0}" -f $all.Count)
foreach ($e in $all) {
  $ct = $e.Current.ControlType.ProgrammaticName
  $nm = $e.Current.Name
  $val = ''
  try { $vp = $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern); $val = $vp.Current.Value } catch {}
  $cls = $e.Current.ClassName
  if ($ct -match 'Edit|List|ListItem|Button|Text|Tree|TreeItem|ComboBox|Pane|Group|TitleBar') {
    if ($nm -or $val) {
      Write-Output ("  [{0}] cls={1} name='{2}' value='{3}'" -f $ct, $cls, $nm, $val)
    }
  }
}
