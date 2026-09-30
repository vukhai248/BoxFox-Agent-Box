# ==============================================================================
# BoxFox Agent Box -- All-in-One Startup Script
# ==============================================================================
param (
    [switch]$Rebuild
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$RootDir = Split-Path -Path $ScriptDir -Parent

Write-Host ""
Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host "         BoxFox Agent Box -- Project Launcher                      " -ForegroundColor Yellow
Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------------------------
# 1. Check & Add Docker to PATH if needed
# ------------------------------------------------------------------------------
$DockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $DockerCmd) {
    $CandidatePaths = @(
        "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin",
        "$env:ProgramFiles\Docker\Docker\resources\bin",
        "C:\Program Files\Docker\Docker\resources\bin"
    )
    foreach ($p in $CandidatePaths) {
        if ($p -and (Test-Path "$p\docker.exe")) {
            $env:PATH = $p + ";" + $env:PATH
            break
        }
    }
}

# ------------------------------------------------------------------------------
# 2. Check & Start Docker Sandbox
# ------------------------------------------------------------------------------
Write-Host "[1/3] Checking Docker Sandbox status..." -ForegroundColor Cyan

$DockerRunning = $false
try {
    $dockerInfoJob = Start-Job -ScriptBlock { docker info 2>&1 }
    $finished = Wait-Job $dockerInfoJob -Timeout 4
    if ($finished) {
        $infoResult = Receive-Job $dockerInfoJob
        if ($LASTEXITCODE -eq 0 -or ($infoResult -match "Server Version" -or $infoResult -match "Containers")) {
            $DockerRunning = $true
        }
    }
    Remove-Job -Force $dockerInfoJob -ErrorAction SilentlyContinue
} catch {
    $DockerRunning = $false
}

$DockerDir = Join-Path $RootDir "deploy\docker"

if ($DockerRunning) {
    Write-Host "  -> Docker Desktop: RUNNING" -ForegroundColor Green
    
    $ImageExists = $false
    try {
        $inspectResult = docker image inspect agentbox-sandbox:latest 2>&1
        if ($LASTEXITCODE -eq 0) {
            $ImageExists = $true
        }
    } catch {
        $ImageExists = $false
    }
    
    Push-Location $DockerDir
    try {
        if ($Rebuild) {
            Write-Host "  -> Clean rebuild requested. Rebuilding image..." -ForegroundColor Yellow
            docker compose build --no-cache
        } else {
            Write-Host "  -> Starting Sandbox container (syncing latest config layers)..." -ForegroundColor Cyan
        }
        
        if ($ImageExists -and -not $Rebuild) {
            docker compose up -d
        } else {
            docker compose up -d --build
        }
        $WorkerSrc = Join-Path $RootDir "backend\src\agentbox\sandbox\worker.py"
        if (Test-Path $WorkerSrc) {
            docker cp $WorkerSrc agentbox-box:/tmp/boxfox-worker.py 2>$null
        }
        Write-Host "  -> [OK] Sandbox LIVE: IDE on http://localhost:8080 | VNC on localhost:5900 | API on :8081" -ForegroundColor Green
    } catch {
        Write-Host "  -> [WARN] Could not start Docker container: $_" -ForegroundColor Yellow
    } finally {
        Pop-Location
    }
} else {
    Write-Host "  -> [INFO] Docker Desktop is not active. Native Router still runs on the host." -ForegroundColor Yellow
    Write-Host "     (Open Docker Desktop and re-run this script anytime for Live Sandbox)" -ForegroundColor DarkGray
}

Write-Host ""

# ------------------------------------------------------------------------------
# 3. Check Frontend Dependencies
# ------------------------------------------------------------------------------
Write-Host "[2/3] Checking Frontend dependencies..." -ForegroundColor Cyan
$FrontendDir = Join-Path $RootDir "frontend"
$NodeModulesDir = Join-Path $FrontendDir "node_modules"

if (-not (Test-Path $NodeModulesDir)) {
    Write-Host "  -> node_modules missing. Running npm install..." -ForegroundColor Yellow
    Push-Location $FrontendDir
    try {
        npm.cmd install
        Write-Host "  -> [OK] Dependencies installed." -ForegroundColor Green
    } finally {
        Pop-Location
    }
} else {
    Write-Host "  -> [OK] Dependencies ready." -ForegroundColor Green
}

Write-Host ""

# ------------------------------------------------------------------------------
# 4. Start Vite Dev Server & Open Browser (Auto Clean on Exit)
# ------------------------------------------------------------------------------
Write-Host "[3/3] Starting Frontend Dev Server..." -ForegroundColor Cyan
Write-Host ""
Write-Host "  -> Local Application: http://localhost:3100/" -ForegroundColor Green
Write-Host "  -> Press Ctrl + C or close this window to stop everything." -ForegroundColor DarkGray
Write-Host ""

$RouterProcess = $null
$HarnessProcess = $null
$RouterDir = Join-Path $RootDir "router"
$RouterLogDir = Join-Path $env:LOCALAPPDATA "BoxFox\logs"
New-Item -ItemType Directory -Path $RouterLogDir -Force | Out-Null
try {
    $NodeCommand = Get-Command node -ErrorAction Stop
    $NodeMajor = [int]((& node --version).TrimStart('v').Split('.')[0])
    if ($NodeMajor -lt 24) { throw "Native Router requires Node.js 24 or newer." }
    $ExistingRouter = $null
    try { $ExistingRouter = Invoke-RestMethod -Uri "http://127.0.0.1:3101/api/router/health" -TimeoutSec 2 } catch {}
    if ($ExistingRouter.status -eq 'ok' -and $ExistingRouter.version -eq '0.1.0') {
        Write-Host "  -> Reusing healthy BoxFox Router on :3101." -ForegroundColor Green
    } else {
        $RouterProcess = Start-Process -FilePath $NodeCommand.Source -ArgumentList @('src/main.mjs') -WorkingDirectory $RouterDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $RouterLogDir 'router.stdout.log') -RedirectStandardError (Join-Path $RouterLogDir 'router.stderr.log')
        $RouterHealthy = $false
        for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
            if ($RouterProcess.HasExited) { throw "Router exited. See $RouterLogDir\router.stderr.log" }
            try { $Health = Invoke-RestMethod -Uri "http://127.0.0.1:3101/api/router/health" -TimeoutSec 1; if ($Health.status -eq 'ok') { $RouterHealthy = $true; break } } catch {}
            Start-Sleep -Milliseconds 250
        }
        if (-not $RouterHealthy) { throw "Router health check failed. See $RouterLogDir\router.stderr.log" }
    }
} catch {
    if ($RouterProcess -and -not $RouterProcess.HasExited) { Stop-Process -Id $RouterProcess.Id }
    Write-Error "BoxFox startup failed: $_"
    exit 1
}

try {
    $HarnessHealth = $null
    try { $HarnessHealth = Invoke-RestMethod 'http://127.0.0.1:3102/api/agent/health' -TimeoutSec 2 } catch {}
    if ($HarnessHealth.service -ne 'boxfox-harness') {
        $PythonPath = $null
        $CandidatePythons = @(
            "C:\Users\Admin\anaconda3\envs\DL\python.exe",
            "$env:CONDA_PREFIX\python.exe"
        )
        foreach ($cp in $CandidatePythons) {
            if ($cp -and (Test-Path $cp)) { $PythonPath = $cp; break }
        }
        if (-not $PythonPath) {
            $PythonCommand = Get-Command python -ErrorAction Stop
            $PythonPath = $PythonCommand.Source
        }
        $HarnessProcess = Start-Process -FilePath $PythonPath -ArgumentList @('scripts/run-harness.py') -WorkingDirectory $RootDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $RouterLogDir 'harness.stdout.log') -RedirectStandardError (Join-Path $RouterLogDir 'harness.stderr.log')
        $HarnessReady = $false
        for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
            if ($HarnessProcess.HasExited) { throw 'Harness exited; install backend/requirements.txt and inspect harness.stderr.log.' }
            try { $HarnessHealth = Invoke-RestMethod 'http://127.0.0.1:3102/api/agent/health' -TimeoutSec 1; if ($HarnessHealth.status -eq 'ok') { $HarnessReady = $true; break } } catch {}
            Start-Sleep -Milliseconds 250
        }
        if (-not $HarnessReady) { throw 'Harness health failed on :3102.' }
    }
    Write-Host '  -> Harness engine available on :3102.' -ForegroundColor Green
} catch {
    if ($HarnessProcess -and -not $HarnessProcess.HasExited) { Stop-Process -Id $HarnessProcess.Id }
    if ($RouterProcess -and -not $RouterProcess.HasExited) { Stop-Process -Id $RouterProcess.Id }
    Write-Error "BoxFox harness startup failed: $_"
    exit 1
}

Push-Location $FrontendDir
try {
    Start-Job -ScriptBlock {
        Start-Sleep -Seconds 2
        Start-Process "http://localhost:3100/"
    } | Out-Null
    npm.cmd run dev
} finally {
    Pop-Location
    if ($HarnessProcess -and -not $HarnessProcess.HasExited) { Stop-Process -Id $HarnessProcess.Id }
    if ($RouterProcess -and -not $RouterProcess.HasExited) { Stop-Process -Id $RouterProcess.Id }
    if ($DockerRunning) {
        Write-Host ""
        Write-Host "Stopping Docker Sandbox containers..." -ForegroundColor Cyan
        Push-Location $DockerDir
        try {
            docker compose down
            Write-Host "[OK] Docker containers stopped." -ForegroundColor Green
        } catch {
            # ignore
        } finally {
            Pop-Location
        }
    }
    Write-Host "[OK] BoxFox Agent Box stopped cleanly." -ForegroundColor Green
}
