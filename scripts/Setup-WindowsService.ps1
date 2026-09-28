<#
.SYNOPSIS
  Interactive wizard: registers the DrugsRus Invoice API as a Windows
  Service (via NSSM) so it auto-starts on boot and auto-restarts on crash.

.DESCRIPTION
  Pure PowerShell, no Git/Git Bash required. Walks you through installing
  NSSM (if needed) and wiring up the service. The actual service-install
  commands need an elevated (Run as Administrator) PowerShell — this
  wizard tells you exactly what to run and waits for confirmation at
  each step rather than trying to self-elevate.

.USAGE
  From the project root, in a normal PowerShell:
    powershell -ExecutionPolicy Bypass -File .\scripts\Setup-WindowsService.ps1
  or, if your execution policy already allows local scripts:
    .\scripts\Setup-WindowsService.ps1
#>

$ErrorActionPreference = 'Stop'

# ──────────────────────────────────────────────────────────────────────────
# Wizard library (small, self-contained — no external deps)
# ──────────────────────────────────────────────────────────────────────────

$Script:StageIndex = 0
$Script:TotalStages = 9

function Write-Banner([string]$Title) {
    Clear-Host
    Write-Host ""
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host "  $($Script:TotalStages) stages" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  You drive the elevated PowerShell window; this wizard tells you" -ForegroundColor DarkGray
    Write-Host "  exactly what to run there and waits for you to confirm it worked." -ForegroundColor DarkGray
    Write-Host "  Stop any time with Ctrl+C and re-run later." -ForegroundColor DarkGray
    Read-Host "  Ready to start? Press Enter to continue" | Out-Null
}

function Start-Stage([string]$Name) {
    Clear-Host
    $Script:StageIndex++
    Write-Host ""
    Write-Host "  Stage $($Script:StageIndex)/$($Script:TotalStages) - $Name" -ForegroundColor Cyan
}

function Say([string]$Text)  { Write-Host "  $Text" }
function Step([string]$Text) { Write-Host "  * $Text" -ForegroundColor Blue }
function Note([string]$Text) { Write-Host "  $Text" -ForegroundColor DarkGray }
function Warn([string]$Text) { Write-Host "  ! $Text" -ForegroundColor Yellow }

function Confirm-Step([string]$Question) {
    $reply = Read-Host "  ? $Question [y/N]"
    return $reply -match '^[Yy]'
}

function Pause-Step([string]$Message = "Press Enter to continue") {
    Read-Host "  $Message" | Out-Null
}

function Open-Url([string]$Url) {
    Write-Host "  -> opening $Url" -ForegroundColor Green
    try { Start-Process $Url | Out-Null } catch { Warn "couldn't open a browser; visit it manually: $Url" }
}

function Show-Finish {
    Clear-Host
    Write-Host ""
    Write-Host "  Setup complete" -ForegroundColor Green
    Write-Host ""
}

# ──────────────────────────────────────────────────────────────────────────
# STAGES
# ──────────────────────────────────────────────────────────────────────────

$ProjectDir  = Split-Path -Parent $PSScriptRoot
$PythonExe   = Join-Path $ProjectDir '.venv\Scripts\python.exe'
$ServiceName = 'DrugsRusInvoiceAPI'
$StdoutLog   = Join-Path $ProjectDir 'logs\service_stdout.log'
$StderrLog   = Join-Path $ProjectDir 'logs\service_stderr.log'
$PipelineLog = Join-Path $ProjectDir 'logs\pipeline.log'
$CleanupScript = Join-Path $ProjectDir 'scripts\Cleanup-ApiRun.ps1'
$CleanupTaskName = 'DrugsRusInvoiceAPI-CleanupApiRun'

Write-Banner "DrugsRus Invoice API - Windows Service (NSSM) setup"
Say "Goal: register the FastAPI app as a Windows Service so it auto-starts on"
Say "boot and auto-restarts itself if the process ever crashes."
Note "Every command below needs an ELEVATED (Run as Administrator) PowerShell."
Note "This wizard won't run privileged commands for you - it hands you the"
Note "exact command each time and waits for you to confirm it worked."

# Stage 1: check for NSSM
Start-Stage "Check whether NSSM is already installed"
Say "NSSM (Non-Sucking Service Manager) is the free tool we'll use to wrap"
Say "python.exe as a managed Windows service."
Step "In any PowerShell, run: nssm --version"
$haveNssm = Confirm-Step "Did that print a version number (i.e. NSSM is already installed)?"
if ($haveNssm) { Note "Great - skipping the install stage." }

# Stage 2: install NSSM
if (-not $haveNssm) {
    Start-Stage "Install NSSM"
    Say "Pick whichever install path is easiest for you:"
    Step "Option A - winget (if you have it): winget install NSSM.NSSM"
    Step "Option B - choco (if you have it):  choco install nssm -y"
    Step "Option C - manual download:"
    Open-Url "https://nssm.cc/download"
    Note "  Download the latest zip, extract it, and copy the win64\nssm.exe"
    Note "  into a stable folder, e.g. C:\nssm\nssm.exe, then add C:\nssm to"
    Note "  your System PATH (Settings -> Environment Variables)."
    Pause-Step "Once nssm --version works from a fresh PowerShell, press Enter to continue."
} else {
    Start-Stage "Install NSSM"
    Note "Already installed - nothing to do here."
}

# Stage 3: open an elevated terminal
Start-Stage "Open an elevated PowerShell"
Say "Installing a Windows service needs administrator rights."
Step "Press Start, type PowerShell, right-click it, choose 'Run as administrator'."
Step "In that elevated window, cd to the project folder:"
Note "  cd `"$ProjectDir`""
Pause-Step "Press Enter once you have an elevated PowerShell open at the project folder."

# Stage 4: install the service
Start-Stage "Register the service with NSSM"
Say "This tells NSSM to run the venv's python.exe with app.py as the argument,"
Say "using the project folder as the working directory."
Step "Run:"
Note "  nssm install $ServiceName `"$PythonExe`" `"app.py`""
Step "Then set the working directory so relative paths (logs\, .env) resolve:"
Note "  nssm set $ServiceName AppDirectory `"$ProjectDir`""
Pause-Step "Press Enter once both commands have run without error."

# Stage 5: redirect stdout/stderr
Start-Stage "Point NSSM's own stdout/stderr at log files"
Say "The app already logs to logs\pipeline.log itself, but NSSM can also"
Say "capture raw stdout/stderr (e.g. startup tracebacks before logging init)."
Step "Run:"
Note "  nssm set $ServiceName AppStdout `"$StdoutLog`""
Note "  nssm set $ServiceName AppStderr `"$StderrLog`""
Pause-Step "Press Enter once both commands have run."

# Stage 6: auto-start + auto-restart
Start-Stage "Enable auto-start on boot and auto-restart on crash"
Step "Auto-start the service when Windows boots (even before login):"
Note "  nssm set $ServiceName Start SERVICE_AUTO_START"
Step "Restart the app automatically if it ever exits/crashes:"
Note "  nssm set $ServiceName AppExit Default Restart"
Note "  (optional) throttle restarts if it crash-loops:"
Note "  nssm set $ServiceName AppThrottle 15000"
Pause-Step "Press Enter once these commands have run."

# Stage 7: start and verify
Start-Stage "Start the service and verify it's running"
Step "Start it:"
Note "  nssm start $ServiceName"
Step "Check Windows sees it as running:"
Note "  sc query $ServiceName"
Step "Confirm the API itself responds (any PowerShell, elevation not needed):"
Note "  Invoke-WebRequest http://localhost:8001/docs -UseBasicParsing"
if (Confirm-Step "Did the service report RUNNING and /docs respond?") {
    Note "Service is live. It will now survive reboots and crashes automatically."
} else {
    Warn "Check logs before moving on:"
    Note "  Get-Content `"$StdoutLog`" -Tail 50"
    Note "  Get-Content `"$StderrLog`" -Tail 50"
    Note "  Get-Content `"$PipelineLog`" -Tail 50"
}

# Stage 8: schedule api_run\ cleanup
Start-Stage "Schedule automatic api_run\ cleanup"
Say "Every request writes a timestamped folder under api_run\. Left alone this"
Say "grows forever. This registers a Scheduled Task that keeps only the 50"
Say "most recent folders, deleting older ones."
Step "Run (elevated PowerShell, so it can run whether or not you're logged in):"
Note "  `$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-ExecutionPolicy Bypass -File `"$CleanupScript`"'"
Note "  `$trigger = New-ScheduledTaskTrigger -Daily -At 3am"
Note "  `$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest"
Note "  Register-ScheduledTask -TaskName '$CleanupTaskName' -Action `$action -Trigger `$trigger -Principal `$principal -Description 'Keeps only the newest 50 folders in api_run\'"
if (Confirm-Step "Did Register-ScheduledTask complete without error?") {
    Note "Cleanup is now scheduled to run daily at 3am."
    Step "You can also run it once right now to clean up any existing backlog:"
    Note "  powershell -ExecutionPolicy Bypass -File `"$CleanupScript`""
    if (Confirm-Step "Run it now?") {
        & powershell -ExecutionPolicy Bypass -File $CleanupScript
    }
} else {
    Warn "Skipping - you can register the task manually later, or just run"
    Warn "  $CleanupScript"
    Warn "by hand from time to time."
}

# Stage 9: reference commands
Start-Stage "Reference: managing the service later"
Say "Keep these handy - all require an elevated PowerShell:"
Step "Stop:            nssm stop $ServiceName"
Step "Restart:         nssm restart $ServiceName"
Step "Status:          sc query $ServiceName"
Step "Edit settings:   nssm edit $ServiceName   (opens a small GUI)"
Step "Remove entirely: nssm remove $ServiceName confirm"
Step "Live app logs:   Get-Content `"$PipelineLog`" -Wait -Tail 50"
Step "Run api_run\ cleanup now: powershell -ExecutionPolicy Bypass -File `"$CleanupScript`""
Step "Remove cleanup schedule: Unregister-ScheduledTask -TaskName '$CleanupTaskName' -Confirm:`$false"
Note "Since app.py already rotates logs\pipeline.log itself, that's the best"
Note "place to look for real request/processing errors day to day."

Show-Finish
