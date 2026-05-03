# Stage 1: extract tarball + create venv (fast). pip install runs detached
# in a separate cmd window so the WinRM call returns within seconds.
# Caller polls C:\setup\daq_daemon\setup.log for "=== setup done ===".

$ErrorActionPreference = 'Stop'
$root    = 'C:\setup\daq_daemon'
$src     = "$root\src"
$venv    = "$root\venv"
$tarball = 'C:\setup\daq_daemon_pkg.tar.gz'
$logPath = "$root\setup.log"
$script  = "$root\install-deps.ps1"

if (-not (Test-Path $root)) { New-Item -ItemType Directory -Path $root -Force | Out-Null }
function Log([string]$m) {
    $ts = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    "$ts  $m" | Out-File -FilePath $logPath -Append -Encoding utf8
    Write-Host "$ts  $m"
}

Log "=== setup-daq-daemon.ps1 start ==="

# Stop daemon if running
$task = Get-ScheduledTask -TaskName 'PickupEdsDaqDaemon' -ErrorAction SilentlyContinue
if ($task) {
    Log "Stopping existing PickupEdsDaqDaemon task"
    Stop-ScheduledTask -TaskName 'PickupEdsDaqDaemon' -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}
# Best-effort kill of any python in our venv
Get-Process -Name 'python','py' -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and ($_.Path -like "$venv*")
} | Stop-Process -Force -ErrorAction SilentlyContinue

# Extract package
if (Test-Path $src) { Remove-Item -Recurse -Force $src }
New-Item -ItemType Directory -Path $src -Force | Out-Null
Log "Extracting $tarball"
tar -xzf $tarball -C $src
if ($LASTEXITCODE -ne 0) { throw "tar extraction failed" }

# Create venv if absent
if (-not (Test-Path "$venv\Scripts\python.exe")) {
    Log "Creating venv at $venv"
    & py -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
} else {
    Log "Reusing existing venv at $venv"
}

# Build the detached install script.
$pip = "$venv\Scripts\pip.exe"
$installScript = @"
`$ErrorActionPreference = 'Continue'
`$logPath = '$logPath'
function Log(`$m) {
    `$ts = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    "`$ts  `$m" | Out-File -FilePath `$logPath -Append -Encoding utf8
}
Log "Installing Python deps (detached)"
& '$pip' install --upgrade pip --quiet 2>&1 | Out-File -FilePath `$logPath -Append -Encoding utf8
& '$pip' install --quiet ``
    'fastapi>=0.115,<1.0' ``
    'uvicorn>=0.32,<1.0' ``
    'numpy>=2.0,<3.0' ``
    'pydantic>=2.0,<3.0' ``
    'websockets>=13,<16' ``
    'pyserial>=3.5,<4.0' ``
    'nidaqmx>=1.0' 2>&1 | Out-File -FilePath `$logPath -Append -Encoding utf8
if (`$LASTEXITCODE -ne 0) { Log "WARN: pip install rc=`$LASTEXITCODE" }
Log "Probing imports"
& '$venv\Scripts\python.exe' -c "import fastapi, uvicorn, nidaqmx, serial, websockets, pydantic; print('imports ok')" 2>&1 | Out-File -FilePath `$logPath -Append -Encoding utf8
Log "=== setup done ==="
"@
$installScript | Out-File -FilePath $script -Encoding utf8 -Force

# Fire-and-forget. Use Start-Process with -PassThru so we know the PID; do not -Wait.
Log "Launching detached: powershell -File $script"
Start-Process -FilePath 'powershell.exe' `
    -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',$script `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -PassThru | Out-Null

Log "Stage 1 complete; pip install running in background. Poll setup.log for 'setup done'."
Write-Host "Stage 1 done. Detached pip install in progress."
