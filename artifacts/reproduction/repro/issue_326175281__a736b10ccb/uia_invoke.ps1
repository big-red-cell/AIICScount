# UIA: find the "ANTIBOT CHECK" bookmark bar item and invoke it
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$condName = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, 'ANTIBOT CHECK')
$el = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condName)
if (-not $el) { Write-Output 'UIA_NOT_FOUND'; exit 1 }
Write-Output ('UIA_FOUND: name=' + $el.Current.Name + ' controlType=' + $el.Current.ControlType.ProgrammaticName + ' enabled=' + $el.Current.IsEnabled)
try {
  $invoke = $el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
  $invoke.Invoke()
  Write-Output 'UIA_INVOKED'
} catch {
  Write-Output ('UIA_INVOKE_FAILED: ' + $_.Exception.Message)
  exit 1
}
