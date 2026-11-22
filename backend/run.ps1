# Flow Assistente — sobe o backend no Windows (porta 8000)
# Uso: cd backend; .\run.ps1            (parâmetros: -Reset recria o banco, -SemReload, -Porta 8000)
param(
    [switch]$Reset,
    [switch]$SemReload,
    [int]$Porta = 8000
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Criando ambiente virtual (.venv)..." -ForegroundColor Cyan
    python -m venv .venv
    if (-not $?) { throw "Falha ao criar o .venv. Verifique se o Python 3.12 está instalado." }
}

Write-Host "Instalando dependências..." -ForegroundColor Cyan
& $py -m pip install -q --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Falha no pip install." }

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Criado .env a partir do .env.example (modo mock por padrão)." -ForegroundColor Yellow
}

$resetPy = if ($Reset) { "True" } else { "False" }
Write-Host "Preparando banco SQLite (schema + seed)..." -ForegroundColor Cyan
& $py -c "from app.agent.deps import init_db; init_db(reset=$resetPy); print('Banco OK')"
if ($LASTEXITCODE -ne 0) { throw "Falha ao criar o banco." }

Write-Host "Montando índice do RAG..." -ForegroundColor Cyan
& $py -c "from app.agent.deps import build_index; print('Índice OK' if build_index(force=$resetPy) else 'RAG indisponível: usando busca simples')"
if ($LASTEXITCODE -ne 0) { Write-Host "Aviso: falha ao montar o índice; a API sobe mesmo assim." -ForegroundColor Yellow }

$modo = & $py -c "from app import config; print(config.LLM_MODE)"
Write-Host ""
Write-Host "Flow Assistente em http://localhost:$Porta  (docs: /docs, modo LLM: $modo)" -ForegroundColor Green
$args_uv = @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$Porta")
if (-not $SemReload) { $args_uv += "--reload" }
& $py @args_uv
