# Register / refresh the PickupEdsDaqDaemon scheduled task.
#
# Triggers at startup (60 s after PickupEdsFirstBoot has had a chance to
# do its NI service kick), runs as SYSTEM. Auto-restart on failure.

$ErrorActionPreference = 'Stop'
$taskName = 'PickupEdsDaqDaemon'
$venvPython = 'C:\setup\daq_daemon\venv\Scripts\python.exe'
$srcDir   = 'C:\setup\daq_daemon\src'

if (-not (Test-Path $venvPython)) {
    throw "venv python not found at $venvPython; run setup-daq-daemon.ps1 first"
}
if (-not (Test-Path "$srcDir\pickup_eds\daq_daemon\__main__.py")) {
    throw "daq_daemon package not found under $srcDir"
}

# Kill old task
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# Wrap the venv python under cmd to set PYTHONPATH first
$cmd = "/c set PYTHONPATH=$srcDir && `"$venvPython`" -m pickup_eds.daq_daemon --host 0.0.0.0 --port 8765 > C:\setup\daq_daemon\daemon.log 2>&1"
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $cmd

$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = 'PT1M'   # 60 s after boot, so PickupEdsFirstBoot finishes first

$principal = New-ScheduledTaskPrincipal `
    -UserId 'SYSTEM' `
    -LogonType ServiceAccount `
    -RunLevel Highest

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Days 30) `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'pickup-eds DAQ daemon (FastAPI :8765)' | Out-Null

Write-Host "Registered scheduled task '$taskName'."
# Trigger now so we don't have to reboot to test.
Start-ScheduledTask -TaskName $taskName
Write-Host "Task started; daemon log -> C:\setup\daq_daemon\daemon.log"
