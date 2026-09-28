<#
.SYNOPSIS
  Deletes the oldest folders under api_run\ once the total count exceeds a
  threshold (default 50), keeping the most recent ones.

.DESCRIPTION
  Each API request creates a timestamped folder under api_run\
  (e.g. invoice_20260924_114321). Left unchecked this grows forever. This
  script sorts the folders by creation time and removes the oldest ones so
  at most -Keep folders remain. Intended to be run on a recurring schedule
  (see Setup-WindowsService.ps1, which registers this as a Scheduled Task).

.USAGE
  powershell -ExecutionPolicy Bypass -File .\scripts\Cleanup-ApiRun.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\Cleanup-ApiRun.ps1 -Keep 50
#>

param(
    [int]$Keep = 50
)

$ErrorActionPreference = 'Stop'

$ProjectDir = Split-Path -Parent $PSScriptRoot
$ApiRunDir  = Join-Path $ProjectDir 'api_run'

if (-not (Test-Path $ApiRunDir)) {
    Write-Host "api_run\ does not exist yet, nothing to clean up."
    exit 0
}

$entries = Get-ChildItem -Path $ApiRunDir -Directory | Sort-Object CreationTime

$excess = $entries.Count - $Keep
if ($excess -le 0) {
    Write-Host "api_run\ has $($entries.Count) folder(s), under the limit of $Keep. Nothing to remove."
    exit 0
}

$toRemove = $entries | Select-Object -First $excess
Write-Host "api_run\ has $($entries.Count) folder(s), removing the oldest $excess to get back to $Keep."

foreach ($dir in $toRemove) {
    try {
        Remove-Item -Path $dir.FullName -Recurse -Force
        Write-Host "  removed: $($dir.Name)"
    } catch {
        Write-Warning "  failed to remove $($dir.Name): $_"
    }
}
