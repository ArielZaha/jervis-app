# Install test for the Windows build, the way a user installs it:
#   run "Jervis Setup.exe" silently, check the files and shortcuts, run the engine's self-test, start Jervis, check the
#   engine comes up, quit it, check nothing is left running; install again over it (an update) and start and quit
#   once more; uninstall, check the app and shortcuts are gone.
#     pwsh tests/installer/windows_smoke.ps1 -Installer "release/Jervis Setup.exe"
param([Parameter(Mandatory = $true)][string]$Installer)
$ErrorActionPreference = 'Stop'
function Fail($message) { Write-Host "FAIL: $message"; exit 1 }

function Show-Crashes {
  # Which program and module crashed, from Windows' own crash records (Application Error / Windows Error Reporting)
  Get-WinEvent -FilterHashtable @{ LogName = 'Application'; Id = 1000, 1001; StartTime = (Get-Date).AddMinutes(-15) } `
    -ErrorAction SilentlyContinue | Select-Object -First 4 | ForEach-Object { Write-Host "---- event $($_.Id)"; Write-Host $_.Message }
}

function Install-Jervis($what) {
  $started = Get-Date
  $p = Start-Process -FilePath $Installer -ArgumentList '/S' -PassThru -Wait
  if ($p.ExitCode -ne 0) { Show-Crashes; Fail "the installer exited with $($p.ExitCode) ($what)" }
  Write-Host "$what in $([int]((Get-Date) - $started).TotalSeconds)s"
}

$sizeMb = [math]::Round((Get-Item $Installer).Length / 1MB)
Write-Host "installer: $Installer ($sizeMb MB)"
Install-Jervis 'installed'

$exe = Get-ChildItem "$env:LOCALAPPDATA\Programs" -Recurse -Filter 'Jervis.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $exe) { Fail 'Jervis.exe was not installed under %LOCALAPPDATA%\Programs' }
$dir = $exe.DirectoryName
Write-Host "app: $($exe.FullName)"
$engine = Join-Path $dir 'resources\backend\jervis-backend.exe'
if (-not (Test-Path $engine)) { Fail 'the engine (jervis-backend.exe) is missing' }
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Jervis.lnk'
$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Jervis.lnk'
foreach ($shortcut in @($desktop, $startMenu)) { if (-not (Test-Path $shortcut)) { Fail "shortcut missing: $shortcut" } }
Write-Host 'shortcuts: desktop and Start menu'

$env:JERVIS_DATA_DIR = Join-Path $env:RUNNER_TEMP 'jervis-selftest'
$report = & $engine --selftest | Select-String '^SELFTEST'
Remove-Item Env:\JERVIS_DATA_DIR
if ($LASTEXITCODE -ne 0) { Write-Host $report; Fail 'the engine self-test failed' }
Write-Host 'engine self-test: passed'

function Start-And-Quit($when) {
  # Start it the way sign-in does (hidden in the tray), without the microphone or the AI download.
  $env:JERVIS_NO_AI_SETUP = '1'; $env:JERVIS_AUDIO = 'off'
  $log = Join-Path $env:APPDATA 'Jervis\logs\jervis.log'
  if (Test-Path $log) { Remove-Item $log }
  $started = Get-Date
  Start-Process -FilePath $exe.FullName -ArgumentList '--hidden'
  $ready = $false
  for ($i = 0; $i -lt 120; $i++) {
    if ((Test-Path $log) -and (Select-String -Path $log -Pattern 'listener is ready' -Quiet)) { $ready = $true; break }
    Start-Sleep -Seconds 1
  }
  if (-not $ready) {
    Get-Content (Join-Path $env:APPDATA 'Jervis\logs\window.log') -ErrorAction SilentlyContinue | Select-Object -Last 30
    Get-Content $log -ErrorAction SilentlyContinue | Select-Object -Last 40
    Fail "the engine did not start ($when)"
  }
  Write-Host "engine started in $([int]((Get-Date) - $started).TotalSeconds)s ($when)"
  if (-not (Get-Process -Name 'jervis-backend' -ErrorAction SilentlyContinue)) { Fail "engine process missing ($when)" }

  & $exe.FullName --quit
  for ($i = 0; $i -lt 30; $i++) {
    if (-not (Get-Process -Name 'Jervis' -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Seconds 1
  }
  if (Get-Process -Name 'Jervis' -ErrorAction SilentlyContinue) { Fail "Jervis did not quit ($when)" }
  Start-Sleep -Seconds 2
  if (Get-Process -Name 'jervis-backend' -ErrorAction SilentlyContinue) { Fail "the engine was left running after quitting ($when)" }
  Write-Host "quit: window and engine both stopped ($when)"
}

Start-And-Quit 'fresh install'
Install-Jervis 'installed again over it (update)'
if (-not (Test-Path $exe.FullName)) { Fail 'Jervis.exe is missing after installing over the old copy' }
Start-And-Quit 'after the update'

$uninstaller = Join-Path $dir 'Uninstall Jervis.exe'
if (-not (Test-Path $uninstaller)) { Fail 'the uninstaller is missing' }
Start-Process -FilePath $uninstaller -ArgumentList '/S' -Wait
for ($i = 0; $i -lt 30; $i++) { if (-not (Test-Path $exe.FullName)) { break }; Start-Sleep -Seconds 1 }
if (Test-Path $exe.FullName) { Fail 'Jervis.exe is still there after uninstalling' }
foreach ($shortcut in @($desktop, $startMenu)) { if (Test-Path $shortcut) { Fail "shortcut left behind: $shortcut" } }
Write-Host 'uninstall: app and shortcuts removed (settings and history are kept in %APPDATA%\Jervis)'
Write-Host 'PASS'
