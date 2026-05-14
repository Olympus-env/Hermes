Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root "frontend"
$deps = "D:\HermesDeps"
$tooling = Join-Path $deps "tooling"
$cache = Join-Path $deps "install-cache"

$env:npm_config_cache = Join-Path $cache "npm"
$env:CARGO_HOME = Join-Path $tooling "cargo"
$env:CARGO_TARGET_DIR = Join-Path $tooling "cargo-target"
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $tooling "ms-playwright"
$env:OLLAMA_MODELS = Join-Path $deps "ollama\models"

New-Item -ItemType Directory -Force `
  -Path $env:npm_config_cache, $env:CARGO_HOME, $env:CARGO_TARGET_DIR, `
        $env:PLAYWRIGHT_BROWSERS_PATH, $env:OLLAMA_MODELS | Out-Null

Push-Location $frontend
try {
  npm run tauri -- dev
} finally {
  Pop-Location
}
