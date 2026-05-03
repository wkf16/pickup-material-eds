# pickup-eds first-boot recovery for Windows VM (pickup-win10-ltsc).
#
# Runs at system startup as SYSTEM via the PickupEdsFirstBoot scheduled
# task. Idempotent: safe to run repeatedly. Logs to C:\setup\nirestore.log.
#
# Steps:
#   1. Start every NI service we know to need.
#   2. Wait briefly for USB plug-in events from the host's
#      pickup-eds-vm-recovery.service detach/attach cycle.
#   3. Probe nidaqmx for Dev1; if absent, kick PnP rescan and retry.
#
# Failure mode: log everything, exit 0 even on partial failure. The
# Linux side daq daemon will report bridge=error if hardware truly
# missing; we don't want a Stop-The-World on first boot.

$ErrorActionPreference = 'Continue'
$logPath = 'C:\setup\nirestore.log'
$logDir  = Split-Path $logPath -Parent
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Log([string]$msg) {
    $ts = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    "$ts  $msg" | Out-File -FilePath $logPath -Append -Encoding utf8
    Write-Host "$ts  $msg"
}

Log "=== nirestore.ps1 start (pid=$PID, user=$env:USERNAME) ==="

# 1. Start NI services.
$services = @(
    'nipalk',          # PAL kernel driver - critical for USB-6002 firmware upload
    'nidevldu',        # PnP -> MAX bridge (most-often missing-on-boot)
    'niSvcLoc',
    'NIDomainService',
    'mxssvr',
    'nimDNSResponder',
    'nisds',
    'NITaggerService',
    'niroco',
    'NINetworkDiscovery',
    'nipxicmsvc',
    'niauth'
)
foreach ($s in $services) {
    $svc = Get-Service -Name $s -ErrorAction SilentlyContinue
    if ($null -eq $svc) {
        Log "  $s : NOT INSTALLED"
        continue
    }
    if ($svc.Status -eq 'Running') {
        Log "  $s : already Running"
    } else {
        try {
            Start-Service -Name $s -ErrorAction Stop
            Log "  $s : started"
        } catch {
            Log "  $s : Start-Service failed: $($_.Exception.Message)"
        }
    }
}

# 2. Give the host's USB detach/attach cycle a moment to complete.
Log "Sleeping 8 s for USB passthrough settle..."
Start-Sleep -Seconds 8

# 3. Probe nidaqmx; if no Dev1, retry once after pnpunum.
function Probe-NIDAQ {
    $py = (Get-Command py.exe -ErrorAction SilentlyContinue).Source
    if (-not $py) { $py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
    if (-not $py) {
        Log "  python not found on PATH; skipping nidaqmx probe"
        return $null
    }
    $out = & $py -c "import nidaqmx; print(','.join(nidaqmx.system.System.local().devices.device_names))" 2>&1
    return [string]$out
}

$devs = Probe-NIDAQ
Log "nidaqmx probe (attempt 1): '$devs'"

if (-not $devs -or $devs -notmatch 'Dev') {
    Log "No DAQ devices visible; rescanning PnP and retrying..."
    & pnputil /scan-devices 2>&1 | Out-File -FilePath $logPath -Append -Encoding utf8
    Start-Sleep -Seconds 5
    $devs = Probe-NIDAQ
    Log "nidaqmx probe (attempt 2): '$devs'"
}

# 6514 SCPI sanity (best-effort)
$py = (Get-Command py.exe -ErrorAction SilentlyContinue).Source
if ($py) {
    $idn = & $py -c "import serial,time; p=serial.Serial('COM3',9600,timeout=2); p.write(b'*IDN?\r\n'); time.sleep(0.4); print(p.read(p.in_waiting).decode(errors='replace').strip())" 2>&1
    Log "6514 IDN probe (COM3): '$idn'"
}

Log "=== nirestore.ps1 done ==="
exit 0
