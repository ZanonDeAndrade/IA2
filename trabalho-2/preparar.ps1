param([switch]$ComRag)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Verificar-Codigo([string]$Etapa) {
    if ($LASTEXITCODE -ne 0) { throw "Falha em: $Etapa. Verifique a mensagem acima." }
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Instale Node.js 22 ou superior e abra o terminal novamente.' }
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv .venv }
    else { & python -m venv .venv }
    Verificar-Codigo 'criar ambiente Python'
}
$pythonExe = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
& $pythonExe -m pip install -r backend/requirements-web.txt
Verificar-Codigo 'instalar API'
if ($ComRag) {
    & $pythonExe -m pip install -r requirements.txt
    Verificar-Codigo 'instalar dependências completas'
}
$engineExe = Join-Path $PSScriptRoot '.local/stockfish/stockfish/stockfish-windows-x86-64-universal.exe'
if (-not (Test-Path -LiteralPath $engineExe)) {
    New-Item -ItemType Directory -Force -Path '.local/stockfish' | Out-Null
    Write-Host 'Baixando Stockfish 19 do repositório oficial...'
    Invoke-WebRequest -Uri 'https://github.com/official-stockfish/Stockfish/releases/download/sf_19/stockfish-windows-x86-64-universal.zip' -OutFile '.local/stockfish.zip'
    Expand-Archive -LiteralPath '.local/stockfish.zip' -DestinationPath '.local/stockfish' -Force
    if (-not (Test-Path -LiteralPath $engineExe)) { throw 'Executável Stockfish não encontrado após extração.' }
}
if (-not (Test-Path -LiteralPath '.env')) {
    $engineSetting = $engineExe.Replace('\', '/')
    $envText = "STOCKFISH_PATH=$engineSetting`nSQLITE_PATH=.local/lance.sqlite`nPUZZLES_DB=data/puzzles.sqlite`nANALISE_PROFUNDIDADE=12`nANALISE_REVISAO_MOTOR=stockfish19-local`nCHESSCOM_USER_AGENT=`nLLM_PROVIDER=`nLLM_MODEL=`nLLM_API_KEY=`n"
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot '.env'), $envText, [Text.UTF8Encoding]::new($false))
} else { Write-Host '.env existente preservado. Confira STOCKFISH_PATH se mudou de computador.' }
& $pythonExe -m data.scripts.download_puzzles --recorte-versionado
Verificar-Codigo 'preparar puzzles'
if ($ComRag) {
    & $pythonExe -m knowledge_base.index
    Verificar-Codigo 'indexar fichas de conceito'
}
Push-Location frontend
try { & npm.cmd ci; Verificar-Codigo 'instalar frontend'; & npm.cmd run build; Verificar-Codigo 'compilar frontend' }
finally { Pop-Location }
Write-Host 'Pronto. Execute .\iniciar.ps1. Configure o contato Chess.com e o LLM no .env para habilitar todos os serviços.'
