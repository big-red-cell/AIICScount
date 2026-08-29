Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$chromePid = [int]$args[0]
$root = [System.Windows.Automation.AutomationElement]::RootElement
$condPid = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $chromePid)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $condPid)
if (-not $win) { Write-Output "NO WINDOW"; exit 1 }
$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$star = $null
foreach ($el in $all) {
  $n = [string]$el.Current.Name
  if ($el.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and $n.Length -ge 8 -and $n[0] -eq [char]0x4E3A -and $n[1] -eq [char]0x6B64) { $star = $el; break }
}
if (-not $star) { Write-Output "STAR NOT FOUND"; exit 2 }
$star.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
Write-Output ("STAR CLICKED: '" + $star.Current.Name + "'")
Start-Sleep -Seconds 2
$all2 = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$doneName = [string][char]0x5B8C + [char]0x6210
$done = $null
foreach ($el in $all2) {
  $n = [string]$el.Current.Name
  if ($el.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and $n -eq $doneName) { $done = $el; break }
}
if ($done) {
  $done.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
  Write-Output "DONE CLICKED"
} else {
  Write-Output "DONE NOT FOUND"
}