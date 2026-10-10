param(
    [ValidateRange(1024, 65535)][int]$WebPort = 3110,
    [string]$DesktopProfile = (Join-Path $env:LOCALAPPDATA 'BoxFoxDesktopAlpha')
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$machineFile = Join-Path $DesktopProfile 'machine.json'
if (-not (Test-Path -LiteralPath $machineFile)) { throw 'Open BoxFox Desktop first; its machine port configuration is missing.' }
$machine = Get-Content -LiteralPath $machineFile -Raw | ConvertFrom-Json
$gatewayPort = [int]$machine.ports.gateway
if ($gatewayPort -lt 1024 -or $gatewayPort -gt 65535 -or $gatewayPort -eq $WebPort) { throw 'Invalid or conflicting gateway/web port.' }
$gateway = "http://127.0.0.1:$gatewayPort"
$health = Invoke-RestMethod -Uri "$gateway/api/desktop/health" -TimeoutSec 5
if ($health.mode -notin @('host', 'docker')) { throw 'Desktop gateway did not return its execution mode.' }
if (Get-NetTCPConnection -LocalPort $WebPort -State Listen -ErrorAction SilentlyContinue) { throw "Web port $WebPort is occupied; choose another -WebPort." }
$node = (Get-Command node -ErrorAction Stop).Source
$frontend = Join-Path $repoRoot 'frontend'
if (-not (Test-Path -LiteralPath (Join-Path $frontend 'node_modules/vite/bin/vite.js'))) { throw 'Run npm ci in frontend first.' }
$logRoot = Join-Path $repoRoot '.tmp/web-desktop-shared'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$previousGateway = $env:BOXFOX_DESKTOP_GATEWAY
try {
    $env:BOXFOX_DESKTOP_GATEWAY = $gateway
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $process = Start-Process -FilePath $node -ArgumentList @('node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', "$WebPort", '--strictPort') -WorkingDirectory $frontend -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot "$stamp.stdout.log") -RedirectStandardError (Join-Path $logRoot "$stamp.stderr.log")
} finally { $env:BOXFOX_DESKTOP_GATEWAY = $previousGateway }
$ready = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    $process.Refresh()
    if ($process.HasExited) { throw "Web process exited. Read logs in $logRoot." }
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$WebPort/" -UseBasicParsing -TimeoutSec 1
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Milliseconds 250
}
if (-not $ready) {
    $process.Refresh()
    if (-not $process.HasExited) { Stop-Process -Id $process.Id }
    throw "Web did not become ready. Read logs in $logRoot."
}
Write-Output "Web: http://localhost:$WebPort/ | desktop gateway: $gateway | mode: $($health.mode) | PID: $($process.Id)"
Write-Output 'The web UI shares the desktop harness, router, sessions, projects and permissions. Keep Desktop running. No installer is built.'
