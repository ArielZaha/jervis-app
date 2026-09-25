# How reliable is the Windows installer? Installs and uninstalls it several times, and for any failure prints which
# module crashed (from Windows' crash records). Diagnostic only.
#     pwsh tests/installer/windows_stress.ps1 -Installer "release/Jervis Setup.exe" -Rounds 6
param([Parameter(Mandatory = $true)][string]$Installer, [int]$Rounds = 6)
$failures = 0
for ($round = 1; $round -le $Rounds; $round++) {
  $started = Get-Date
  $p = Start-Process -FilePath $Installer -ArgumentList '/S' -PassThru -Wait
  $seconds = [int]((Get-Date) - $started).TotalSeconds
  if ($p.ExitCode -ne 0) {
    $failures++
    Write-Host ("round {0}: install FAILED with 0x{1:X8} after {2}s" -f $round, $p.ExitCode, $seconds)
    Get-WinEvent -FilterHashtable @{ LogName = 'Application'; Id = 1000, 1001; StartTime = $started } `
      -ErrorAction SilentlyContinue | Select-Object -First 3 | ForEach-Object { Write-Host "---- event $($_.Id)"; Write-Host $_.Message }
  } else {
    Write-Host "round ${round}: installed in ${seconds}s"
  }
  $exe = Get-ChildItem "$env:LOCALAPPDATA\Programs" -Recurse -Filter 'Jervis.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($exe) {
    Start-Process -FilePath (Join-Path $exe.DirectoryName 'Uninstall Jervis.exe') -ArgumentList '/S' -Wait
    for ($i = 0; $i -lt 30 -and (Test-Path $exe.FullName); $i++) { Start-Sleep -Seconds 1 }
  }
}
Write-Host "installer failures: $failures of $Rounds"
