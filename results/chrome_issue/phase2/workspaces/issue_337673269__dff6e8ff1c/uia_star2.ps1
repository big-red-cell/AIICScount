Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$chromePid = [int]$args[0]
$outFile = $args[1]
$starName = -join ([char]0x4E3A,[char]0x6B64,[char]0x6807,[char]0x7B7E,[char]0x9875,[char]0x6DFB,[char]0x52A0,[char]0x4E66,[char]0x7B7E)
$root = [System.Windows.Automation.AutomationElement]::RootElement
$condPid = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $chromePid)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $condPid)
if (-not $win) { Write-Output "NO WINDOW"; exit 1 }
$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$star = $null
foreach ($el in $all) {
  if ($el.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and $el.Current.Name -eq $starName) { $star = $el; break }
}
if (-not $star) {
  foreach ($el in $all) {
    if ($el.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and $el.Current.Name.Length -eq 10) { $star = $el; Write-Output "FALLBACK MATCH: name='$($el.Current.Name)'"; break }
  }
}
if (-not $star) { Write-Output "STAR NOT FOUND"; exit 2 }
try {
  $star.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
  Write-Output "STAR CLICKED"
} catch { Write-Output "INVOKE FAILED: $($_.Exception.Message)"; exit 3 }
Start-Sleep -Seconds 2
$lines = New-Object System.Collections.Generic.List[string]
$all2 = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$lines.Add("COUNT: $($all2.Count)")
foreach ($el in $all2) {
  $ct = $el.Current.ControlType.ProgrammaticName -replace 'ControlType\.',''
  $name = $el.Current.Name; $val = ""
  try { $val = $el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value } catch {}
  $aid = $el.Current.AutomationId
  $lines.Add("[{0}] id='{1}' name='{2}' value='{3}'" -f $ct, $aid, $name, $val)
}
[System.IO.File]::WriteAllLines($outFile, $lines, (New-Object System.Text.UTF8Encoding($true)))
Write-Output "DUMPED $outFile"