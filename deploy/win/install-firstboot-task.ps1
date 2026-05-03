# Install/refresh the PickupEdsFirstBoot scheduled task on the Windows VM.
#
# The task runs C:\setup\nirestore.ps1 as SYSTEM at system startup, with
# a 30 s delay so libvirt/USB-passthrough has time to settle. It also
# auto-restarts up to 3 times on failure (5-min interval).
#
# Run from an elevated PowerShell (or via WinRM with admin auth):
#   powershell -ExecutionPolicy Bypass -File install-firstboot-task.ps1

$ErrorActionPreference = 'Stop'
$taskName  = 'PickupEdsFirstBoot'
$scriptPath = 'C:\setup\nirestore.ps1'

if (-not (Test-Path $scriptPath)) {
    throw "expected $scriptPath to exist before installing task"
}

# Drop any old version of the task first so a re-run is fully idempotent.
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task '$taskName'..."
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""

$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = 'PT30S'   # 30 s delay after system start

$principal = New-ScheduledTaskPrincipal `
    -UserId 'SYSTEM' `
    -LogonType ServiceAccount `
    -RunLevel Highest

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Re-prime NI services + USB devices after pickup-win10-ltsc boots' | Out-Null

Write-Host "Registered scheduled task '$taskName'."
Get-ScheduledTask -TaskName $taskName | Format-List TaskName, State, Author
