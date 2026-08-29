param([int]$Hwnd, [int]$Count = 8)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
try {
  $f = [System.Windows.Automation.AutomationElement]::FocusedElement
  Write-Output ("FOCUSED name='{0}' cls={1} ct={2}" -f $f.Current.Name, $f.Current.ClassName, $f.Current.ControlType.ProgrammaticName)
} catch { Write-Output ("FOCUSED err: {0}" -f $_.Exception.Message) }
$wshell = New-Object -ComObject WScript.Shell
$ok = $wshell.AppActivate($Hwnd)
Write-Output ("AppActivate={0}" -f $ok)
Start-Sleep -Milliseconds 500
for ($i = 0; $i -lt $Count; $i++) {
  $wshell.SendKeys('{ENTER}')
  Start-Sleep -Milliseconds 250
}
Write-Output ("sent {0} ENTER presses" -f $Count)
