Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$deps = "D:\HermesDeps"

$env:HERMES_DB_PATH = Join-Path $root "data\hermes.db"
$env:HERMES_STORAGE_PATH = Join-Path $root "data\storage"
$env:HERMES_LOG_PATH = Join-Path $root "data\logs"
$env:PIP_CACHE_DIR = Join-Path $deps "install-cache\pip"
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $deps "tooling\ms-playwright"
$env:OLLAMA_MODELS = Join-Path $deps "ollama\models"
$env:PATH = (Join-Path $deps "ollama\bin") + ";" + $env:PATH

New-Item -ItemType Directory -Force `
  -Path $env:PIP_CACHE_DIR, $env:PLAYWRIGHT_BROWSERS_PATH, $env:OLLAMA_MODELS | Out-Null

Push-Location $backend
try {
  if (-not (Test-Path ".venv")) {
    py -3.12 -m venv .venv
  }
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
  .\.venv\Scripts\python.exe -m uvicorn hermes.main:app `
    --host 127.0.0.1 --port 8000 --reload
} finally {
  Pop-Location
}
