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
        if (-not $ImageExists -or $Rebuild) {
            Write-Host "  -> Image not found or rebuild requested. Building image..." -ForegroundColor Yellow
            docker compose build
        } else {
            Write-Host "  -> Image 'agentbox-sandbox:latest' is ready. Starting container directly..." -ForegroundColor Green
        }
        
        docker compose up -d
        Write-Host "  -> [OK] Sandbox LIVE: IDE on http://localhost:8080 | VNC on localhost:5900" -ForegroundColor Green
    } catch {
        Write-Host "  -> [WARN] Could not start Docker container: $_" -ForegroundColor Yellow
    } finally {
        Pop-Location
    }
} else {
    Write-Host "  -> [INFO] Docker Desktop is not active. Starting in Frontend Mock Mode." -ForegroundColor Yellow
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

Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2
    Start-Process "http://localhost:3100/"
} | Out-Null

Push-Location $FrontendDir
try {
    npm.cmd run dev
} finally {
    Pop-Location
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