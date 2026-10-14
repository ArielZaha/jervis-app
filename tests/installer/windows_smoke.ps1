# Install test for the Windows build, the way people install it:
#   run "Jarvis Setup.exe" silently; check the files and shortcuts; run the engine's self-test; start Jarvis and quit
#   him; install again while he is running (he starts after installing and lives in the tray), which must close him
#   by itself and replace his files; start and quit again; end his window by force and check his engine stops too;
#   uninstall and check the app and shortcuts are gone.
#     pwsh tests/installer/windows_smoke.ps1 -Installer "release/Jarvis Setup.exe"
param([Parameter(Mandatory = $true)][string]$Installer)
$ErrorActionPreference = 'Stop'
function Fail($message) { Write-Host "FAIL: $message"; exit 1 }

function Show-Crashes {
  # Which program and module crashed, from Windows' own crash records (Application Error / Windows Error Reporting)
  Get-WinEvent -FilterHashtable @{ LogName = 'Application'; Id = 1000, 1001; StartTime = (Get-Date).AddMinutes(-15) } `
    -ErrorAction SilentlyContinue | Select-Object -First 4 | ForEach-Object { Write-Host "---- event $($_.Id)"; Write-Host $_.Message }
}

function Install-Jarvis($what) {
  $started = Get-Date
  $p = Start-Process -FilePath $Installer -ArgumentList '/S' -PassThru -Wait
  if ($p.ExitCode -ne 0) { Show-Crashes; Fail "the installer exited with $($p.ExitCode) ($what)" }
  Write-Host "$what in $([int]((Get-Date) - $started).TotalSeconds)s"
}

function Jarvis-Running { [bool](Get-Process -Name 'Jarvis', 'jarvis-backend' -ErrorAction SilentlyContinue) }

$sizeMb = [math]::Round((Get-Item $Installer).Length / 1MB)
Write-Host "installer: $Installer ($sizeMb MB)"
Install-Jarvis 'installed'

$exe = Get-ChildItem "$env:LOCALAPPDATA\Programs" -Recurse -Filter 'Jarvis.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $exe) { Fail 'Jarvis.exe was not installed under %LOCALAPPDATA%\Programs' }
$dir = $exe.DirectoryName
Write-Host "app: $($exe.FullName)"
$engine = Join-Path $dir 'resources\backend\jarvis-backend.exe'
if (-not (Test-Path $engine)) { Fail 'the engine (jarvis-backend.exe) is missing' }
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Jarvis.lnk'
$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Jarvis.lnk'
foreach ($shortcut in @($desktop, $startMenu)) { if (-not (Test-Path $shortcut)) { Fail "shortcut missing: $shortcut" } }
Write-Host 'shortcuts: desktop and Start menu'

$env:JARVIS_DATA_DIR = Join-Path $env:RUNNER_TEMP 'jarvis-selftest'
$report = & $engine --selftest | Select-String '^SELFTEST'
Remove-Item Env:\JARVIS_DATA_DIR
if ($LASTEXITCODE -ne 0) { Write-Host $report; Fail 'the engine self-test failed' }
Write-Host 'engine self-test: passed'

# Started the way sign-in starts him (hidden in the tray), without the microphone or the AI download.
$env:JARVIS_NO_AI_SETUP = '1'; $env:JARVIS_AUDIO = 'off'
$log = Join-Path $env:APPDATA 'Jarvis\logs\jarvis.log'

function Start-Jarvis($when) {
  if (Test-Path $log) { Remove-Item $log }
  $started = Get-Date
  Start-Process -FilePath $exe.FullName -ArgumentList '--hidden'
  for ($i = 0; $i -lt 120; $i++) {
    if ((Test-Path $log) -and (Select-String -Path $log -Pattern 'listener is ready' -Quiet)) {
      if (-not (Get-Process -Name 'jarvis-backend' -ErrorAction SilentlyContinue)) { Fail "engine process missing ($when)" }
      Write-Host "engine started in $([int]((Get-Date) - $started).TotalSeconds)s ($when)"
      return
    }
    Start-Sleep -Seconds 1
  }
  Get-Content (Join-Path $env:APPDATA 'Jarvis\logs\window.log') -ErrorAction SilentlyContinue | Select-Object -Last 30
  Get-Content $log -ErrorAction SilentlyContinue | Select-Object -Last 40
  Fail "the engine did not start ($when)"
}

function Wait-Closed($seconds) {
  for ($i = 0; $i -lt $seconds; $i++) { if (-not (Jarvis-Running)) { return $true }; Start-Sleep -Seconds 1 }
  return -not (Jarvis-Running)
}

function Quit-Jarvis($when) {
  & $exe.FullName --quit
  if (-not (Wait-Closed 30)) { Fail "Jarvis (window or engine) still running after quitting ($when)" }
  Write-Host "quit: window and engine both stopped ($when)"
}

Start-Jarvis 'fresh install'
$run = (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue).Jarvis
if (-not $run -or $run -notmatch '--hidden') { Fail "Jarvis isn't set to start (hidden) when you sign in: '$run'" }
Write-Host "starts at sign-in, hidden: $run"
Quit-Jarvis 'fresh install'

# An update while he runs: the installer closes him (window and engine) by itself and replaces his files.
Start-Jarvis 'before the update'
$marker = Join-Path $dir 'resources\left-from-the-old-version.txt'
Set-Content -Path $marker -Value 'old'
# Antivirus programs block the old uninstaller that electron-builder copies to a temp folder ("old-uninstaller.exe"),
# so the update must not run it. It would delete the whole folder; this probe survives only if it wasn't run.
$probe = Join-Path $dir 'probe\not-removed-by-an-old-uninstaller.txt'
New-Item -ItemType Directory -Force -Path (Split-Path $probe) | Out-Null
Set-Content -Path $probe -Value 'probe'
Install-Jarvis 'installed over a running Jarvis (update)'
if (Test-Path $marker) { Fail 'the update did not replace the old files' }
if (-not (Test-Path $probe)) { Fail 'the update ran the old uninstaller (antivirus programs block it)' }
Remove-Item -Recurse -Force (Split-Path $probe)
$entry = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
  Where-Object { $_.DisplayName -like 'Jarvis*' } | Select-Object -First 1
if (-not $entry -or -not $entry.UninstallString) { Fail 'the update left no uninstall entry' }
Write-Host "update: the old uninstaller wasn't needed; uninstall entry: $($entry.UninstallString)"
if (Jarvis-Running) { Fail 'the old Jarvis is still running after the update' }
if (-not (Test-Path $exe.FullName)) { Fail 'Jarvis.exe is missing after the update' }
Write-Host 'update: the running Jarvis was closed and his files replaced'
Start-Jarvis 'after the update'
Quit-Jarvis 'after the update'

# His window ended by force (Task Manager, a crash): the engine must not keep running on its own.
Start-Jarvis 'before ending the window'
Stop-Process -Name 'Jarvis' -Force
for ($i = 0; $i -lt 15 -and (Get-Process -Name 'jarvis-backend' -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Seconds 1 }
if (Get-Process -Name 'jarvis-backend' -ErrorAction SilentlyContinue) { Fail 'the engine kept running after its window was ended' }
Write-Host "window ended by force: the engine stopped by itself within ${i}s"

$uninstaller = Join-Path $dir 'Uninstall Jarvis.exe'
if (-not (Test-Path $uninstaller)) { Fail 'the uninstaller is missing' }
Start-Jarvis 'before uninstalling'
Start-Process -FilePath $uninstaller -ArgumentList '/S' -Wait
for ($i = 0; $i -lt 30; $i++) { if (-not (Test-Path $exe.FullName)) { break }; Start-Sleep -Seconds 1 }
if (Test-Path $exe.FullName) { Fail 'Jarvis.exe is still there after uninstalling' }
if (Jarvis-Running) { Fail 'Jarvis is still running after uninstalling' }
foreach ($shortcut in @($desktop, $startMenu)) { if (Test-Path $shortcut) { Fail "shortcut left behind: $shortcut" } }
if ((Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue).Jarvis) { Fail 'the sign-in entry was left behind' }
Write-Host 'uninstall (while running): app and shortcuts removed, Jarvis closed (settings and history are kept in %APPDATA%\Jarvis)'
Write-Host 'PASS'
