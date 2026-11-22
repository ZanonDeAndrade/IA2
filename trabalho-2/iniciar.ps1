param([switch]$SemAbrirNavegador)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe') -or -not (Test-Path -LiteralPath 'frontend/node_modules')) { throw 'Execute .\preparar.ps1 primeiro.' }
if (-not (Test-Path -LiteralPath '.env')) { throw 'Execute .\preparar.ps1 para preparar o ambiente local.' }
$apiProcess = $null
$webProcess = $null
New-Item -ItemType Directory -Force -Path '.local/logs' | Out-Null
try {
    if (-not (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue)) {
        $apiProcess = Start-Process -FilePath (Join-Path $PSScriptRoot '.venv/Scripts/python.exe') -ArgumentList @('-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput '.local/logs/api.log' -RedirectStandardError '.local/logs/api-erro.log'
    }
    if (-not (Get-NetTCPConnection -State Listen -LocalPort 5173 -ErrorAction SilentlyContinue)) {
        $nodeExe = (Get-Command node).Source
        $webProcess = Start-Process -FilePath $nodeExe -ArgumentList @('node_modules/vite/bin/vite.js') -WorkingDirectory (Join-Path $PSScriptRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput '.local/logs/frontend.log' -RedirectStandardError '.local/logs/frontend-erro.log'
    }
    $ready = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        try {
            $web = Invoke-WebRequest -Uri 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 2
            $api = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/healthz' -TimeoutSec 2
            if ($web.StatusCode -eq 200 -and $api.status -eq 'ok') { $ready = $true; break }
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'Serviços não ficaram prontos. Confira .local/logs/.' }
    Write-Host 'Lance a Lance: http://127.0.0.1:5173'
    Write-Host 'Mantenha este terminal aberto. Ctrl+C encerra os processos iniciados por este script.'
    if (-not $SemAbrirNavegador) { Start-Process 'http://127.0.0.1:5173' }
    while ($true) {
        Start-Sleep -Seconds 2
        if (($apiProcess -and $apiProcess.HasExited) -or ($webProcess -and $webProcess.HasExited)) { throw 'Um serviço parou. Confira .local/logs/.' }
    }
} finally {
    if ($webProcess -and -not $webProcess.HasExited) { Stop-Process -Id $webProcess.Id }
    if ($apiProcess -and -not $apiProcess.HasExited) { Stop-Process -Id $apiProcess.Id }
}
