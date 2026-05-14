Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$deps = "D:\HermesDeps"
$ollama = Join-Path $deps "ollama\bin\ollama.exe"

if (-not (Test-Path -LiteralPath $ollama)) {
  throw "Ollama introuvable: $ollama"
}

$env:OLLAMA_MODELS = Join-Path $deps "ollama\models"
$env:PATH = (Split-Path -Parent $ollama) + ";" + $env:PATH

New-Item -ItemType Directory -Force -Path $env:OLLAMA_MODELS | Out-Null

Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 2

Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" | ConvertTo-Json -Depth 5
