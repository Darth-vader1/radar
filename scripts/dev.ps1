<#
.SYNOPSIS
    Starts the full RADAR development stack on Windows.

.DESCRIPTION
    1. Starts Docker Desktop if needed, then the radar_postgres and radar_redis containers.
    2. Applies pending database migrations (alembic upgrade head).
    3. Starts, each in its own titled PowerShell window, anything not already running:
         RADAR API, RADAR celery worker, RADAR celery beat, RADAR frontend
       The API uses port 8000 if free (else the next free port up to 8010); the frontend
       uses 3000 (else up to 3010) and is pointed at whichever API port was chosen.
    4. Waits for the API and frontend to respond and opens the app in your browser.

    Safe to run again: running services are detected and left alone (important for beat,
    which must only ever run once). Stop everything with scripts\dev-stop.ps1.

.EXAMPLE
    .\scripts\dev.cmd
    .\scripts\dev.cmd -NoBrowser -SkipMigrations
#>
[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$SkipMigrations
)

# "Continue", not "Stop": in Windows PowerShell 5.1 "Stop" turns any stderr output from
# native commands (docker, alembic) into terminating errors. Failures are checked explicitly.
$ErrorActionPreference = "Continue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPython = Join-Path $Backend "venv\Scripts\python.exe"
$VenvCelery = Join-Path $Backend "venv\Scripts\celery.exe"
$DockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$Containers = @("radar_postgres", "radar_redis")

function Write-Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "    $text" -ForegroundColor Green }
function Write-Note($text) { Write-Host "    $text" -ForegroundColor Yellow }

function Get-ProcessCommandLine([int]$ProcessId) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if ($p) { return [string]$p.CommandLine }
    return ""
}

function Test-IsThisProject([string]$CommandLine) {
    return $CommandLine.ToLower().Contains($Root.ToLower())
}

# True if the process or one of its ancestors belongs to this project folder (by command
# line or executable path). Ancestors matter on Windows: a venv's python.exe is a launcher
# whose child (the real interpreter, which holds the port) runs from the base Python install.
function Test-ProcessBelongsHere([int]$ProcessId) {
    $current = $ProcessId
    for ($depth = 0; $depth -lt 5 -and $current -gt 0; $depth++) {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$current" -ErrorAction SilentlyContinue
        if (-not $p) { return $false }
        if ((Test-IsThisProject ([string]$p.CommandLine)) -or (Test-IsThisProject ([string]$p.ExecutablePath))) { return $true }
        $current = [int]$p.ParentProcessId
    }
    return $false
}

function Test-RadarApi([int]$Port) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/health/live" -TimeoutSec 3
        return $r.service -eq "radar-api"
    } catch { return $false }
}

# Returns @{ Port = <n>; Running = $true|$false }: the port this project's service already
# listens on, or the first free port in the range.
function Find-Port([int]$Start, [int]$End, [switch]$IsApi) {
    for ($port = $Start; $port -le $End; $port++) {
        $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $listener) { return @{ Port = $port; Running = $false } }
        if ($IsApi -and (Test-RadarApi $port)) { return @{ Port = $port; Running = $true } }
        if (Test-ProcessBelongsHere $listener.OwningProcess) { return @{ Port = $port; Running = $true } }
    }
    throw "No free port between $Start and $End."
}

function Test-CeleryRunning([string]$Role) {
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match "celery" -and $_.CommandLine -match "workers\.celery_app\s+$Role" -and
        (Test-ProcessBelongsHere $_.ProcessId)
    }
    return [bool]$procs
}

function Start-Window([string]$Title, [string]$WorkingDirectory, [string]$Command) {
    $script = "`$host.UI.RawUI.WindowTitle = '$Title'; $Command"
    Start-Process (Join-Path $PSHOME "powershell.exe") -WorkingDirectory $WorkingDirectory -ArgumentList @("-NoExit", "-NoProfile", "-Command", $script) | Out-Null
}

function Wait-Http([string]$Url, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5 -MaximumRedirection 0 -ErrorAction Stop
            if ($r.StatusCode -lt 500) { return $true }
        } catch {
            $resp = $_.Exception.Response
            if ($resp -and [int]$resp.StatusCode -lt 500) { return $true }  # redirects/401 still mean "up"
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

# --- Preconditions -------------------------------------------------------------------
if (-not (Test-Path $VenvPython)) {
    throw "backend\venv not found. Set it up first (see docs\DEVELOPMENT.md): python -m venv backend\venv; backend\venv\Scripts\pip install -r backend\requirements-dev.lock"
}
if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
    throw "frontend\node_modules not found. Run: cd frontend; npm ci"
}

# --- 1. Docker, Postgres, Redis ----------------------------------------------------
Write-Step "Docker"
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    if (-not (Test-Path $DockerDesktop)) { throw "Docker Desktop is not running and was not found at '$DockerDesktop'. Start it manually." }
    Write-Note "Docker Desktop is not running; starting it..."
    Start-Process $DockerDesktop
    $deadline = (Get-Date).AddSeconds(180)
    do {
        Start-Sleep -Seconds 3
        docker info *> $null
    } until ($LASTEXITCODE -eq 0 -or (Get-Date) -gt $deadline)
    if ($LASTEXITCODE -ne 0) { throw "Docker did not become ready within 3 minutes." }
}
Write-Ok "Docker is running"

foreach ($name in $Containers) {
    $state = docker inspect -f "{{.State.Running}}" $name 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Container '$name' does not exist. Create it once with: docker compose up -d postgres redis (and match the ports in .env)."
    }
    if ($state -ne "true") { docker start $name | Out-Null; Write-Ok "Started $name" } else { Write-Ok "$name already running" }
}

$deadline = (Get-Date).AddSeconds(60)
do {
    Start-Sleep -Seconds 1
    docker exec radar_postgres pg_isready -q *> $null
} until ($LASTEXITCODE -eq 0 -or (Get-Date) -gt $deadline)
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL did not accept connections within 60 seconds." }
Write-Ok "PostgreSQL is accepting connections"

# --- 2. Migrations -------------------------------------------------------------------
if (-not $SkipMigrations) {
    Write-Step "Database migrations"
    Push-Location $Backend
    try {
        & $VenvPython -m alembic upgrade head 2>&1 | Where-Object { $_ -match "Running upgrade|ERROR|Error" } | ForEach-Object { Write-Host "    $_" }
        if ($LASTEXITCODE -ne 0) { throw "alembic upgrade head failed (run it manually in backend\ to see the full error)." }
    } finally { Pop-Location }
    Write-Ok "Database schema is up to date"
}

# --- 3. Services ---------------------------------------------------------------------
Write-Step "Services"
$api = Find-Port 8000 8010 -IsApi
$apiUrl = "http://127.0.0.1:$($api.Port)"
if ($api.Running) {
    Write-Ok "API already running on port $($api.Port)"
} else {
    if ($api.Port -ne 8000) { Write-Note "Port 8000 is used by another program; using $($api.Port) for the API." }
    Start-Window "RADAR API :$($api.Port)" $Backend ".\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port $($api.Port)"
    Write-Ok "Starting API on port $($api.Port)"
}

if (Test-CeleryRunning "worker") {
    Write-Ok "Celery worker already running"
} else {
    Start-Window "RADAR celery worker" $Backend ".\venv\Scripts\celery.exe -A workers.celery_app worker --pool=solo --loglevel=info"
    Write-Ok "Starting Celery worker"
}

if (Test-CeleryRunning "beat") {
    Write-Ok "Celery beat already running (only one may run)"
} else {
    Start-Window "RADAR celery beat" $Backend ".\venv\Scripts\celery.exe -A workers.celery_app beat --loglevel=info"
    Write-Ok "Starting Celery beat"
}

$web = Find-Port 3000 3010
$webUrl = "http://localhost:$($web.Port)"
if ($web.Running) {
    Write-Ok "Frontend already running on port $($web.Port)"
    Write-Note "If it was started against a different API port, stop it (dev-stop) and rerun this script."
} else {
    Start-Window "RADAR frontend :$($web.Port)" $Frontend "`$env:BACKEND_INTERNAL_URL = 'http://localhost:$($api.Port)'; npx next dev -p $($web.Port)"
    Write-Ok "Starting frontend on port $($web.Port) (proxying /api to port $($api.Port))"
}

# --- 4. Wait and report -----------------------------------------------------------------
Write-Step "Waiting for services"
if (Wait-Http "$apiUrl/api/v1/health/live" 60) { Write-Ok "API is up" } else { Write-Note "API did not respond within 60s; check the 'RADAR API' window." }
if (Wait-Http "$webUrl/login" 180) { Write-Ok "Frontend is up" } else { Write-Note "Frontend did not respond within 3 minutes; check the 'RADAR frontend' window." }

try {
    $ready = Invoke-RestMethod -Uri "$apiUrl/api/v1/health/ready" -TimeoutSec 10
    $deadline = (Get-Date).AddSeconds(30)
    while ($ready.checks.workers_alive -lt 1 -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        $ready = Invoke-RestMethod -Uri "$apiUrl/api/v1/health/ready" -TimeoutSec 10
    }
    Write-Ok ("Readiness: database={0} redis={1} broker={2} workers_alive={3}" -f `
        $ready.checks.database, $ready.checks.redis, $ready.checks.broker, $ready.checks.workers_alive)
} catch {
    Write-Note "Could not read API readiness."
}

Write-Host ""
Write-Host "RADAR is running:" -ForegroundColor Cyan
Write-Host "  App        $webUrl"
Write-Host "  API        $apiUrl   (docs: $apiUrl/docs when DEBUG=true)"
Write-Host "  Stop all   .\scripts\dev-stop.cmd"
if (-not $NoBrowser) { Start-Process $webUrl }
