Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ClassNameProperty, '#32770')
$dlg = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
if (-not $dlg) { Write-Output 'NO_DIALOG_FOUND'; exit 1 }
Write-Output ("DIALOG Name='{0}'" -f $dlg.Current.Name)
# Walk descendants, print interesting ones
$all = $dlg.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
foreach ($el in $all) {
  $ct = $el.Current.ControlType.ProgrammaticName
  $nm = $el.Current.Name
  $val = ''
  try { $vp = $el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern); $val = $vp.Current.Value } catch {}
  $cls = $el.Current.ClassName
  # filter: edits, lists, items, buttons, text with content
  if ($ct -match 'Edit|List|ListItem|Button|Text|Tree|TreeItem|ComboBox|Breadcrumb') {
    if ($nm -or $val) {
      Write-Output ("  [{0}] cls={1} name='{2}' value='{3}'" -f $ct, $cls, $nm, $val)
    }
  }
}
