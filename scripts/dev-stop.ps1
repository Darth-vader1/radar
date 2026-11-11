<#
.SYNOPSIS
    Stops the RADAR development stack started by scripts\dev.ps1.

.DESCRIPTION
    Closes the "RADAR ..." windows and stops this project's API (uvicorn), Celery worker and
    beat, and Next.js dev server, however they were started. Only processes belonging to this
    project folder are touched; other projects (e.g. another app on port 8000) are left alone.

    PostgreSQL and Redis keep running unless you pass -IncludeDatabase.

.EXAMPLE
    .\scripts\dev-stop.cmd
    .\scripts\dev-stop.cmd -IncludeDatabase
#>
[CmdletBinding()]
param([switch]$IncludeDatabase)

$ErrorActionPreference = "Continue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path.ToLower()

$all = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine }
$byId = @{}
foreach ($p in $all) { $byId[[int]$p.ProcessId] = $p }

# True if the process or an ancestor runs from this project folder. Needed because a venv's
# python.exe is a launcher: the real interpreter (child) runs from the base Python install,
# and services started with relative paths don't mention the folder in their command line.
function Test-BelongsHere($proc) {
    $current = $proc
    for ($depth = 0; $depth -lt 5 -and $current; $depth++) {
        if (([string]$current.CommandLine).ToLower().Contains($Root) -or ([string]$current.ExecutablePath).ToLower().Contains($Root)) { return $true }
        $current = $byId[[int]$current.ParentProcessId]
    }
    return $false
}

# 1. The windows opened by dev.ps1 (their command sets a "RADAR ..." window title).
$windows = $all | Where-Object { $_.Name -eq "powershell.exe" -and $_.CommandLine -match "WindowTitle = 'RADAR " }

# 2. This project's services, however they were started (windows, IDE, preview tools).
$services = $all | Where-Object {
    $cmd = $_.CommandLine.ToLower()
    (
        $cmd -match "uvicorn\s+app\.main:app" -or
        $cmd -match "workers\.celery_app" -or
        ($cmd -match "next" -and ($cmd -match "\snext\s+dev" -or $cmd -match "\\next\\dist\\"))
    ) -and (Test-BelongsHere $_)
}

$targets = @($windows) + @($services) | Where-Object { $_ } | Sort-Object ProcessId -Unique
if (-not $targets) {
    Write-Host "No RADAR dev processes are running." -ForegroundColor Yellow
} else {
    foreach ($p in $targets) {
        $label = if ($p.Name -eq "powershell.exe") { ($p.CommandLine -replace ".*WindowTitle = '([^']+)'.*", '$1') } else { $p.Name }
        # /T stops the whole tree (uvicorn's reloader children, next dev's server process).
        taskkill /PID $p.ProcessId /T /F *> $null
        if ($LASTEXITCODE -eq 0) { Write-Host "Stopped $label (pid $($p.ProcessId))" -ForegroundColor Green }
    }
}

if ($IncludeDatabase) {
    foreach ($name in @("radar_postgres", "radar_redis")) {
        docker stop $name *> $null
        if ($LASTEXITCODE -eq 0) { Write-Host "Stopped container $name" -ForegroundColor Green }
    }
} else {
    Write-Host "PostgreSQL and Redis left running (use -IncludeDatabase to stop them)."
}
