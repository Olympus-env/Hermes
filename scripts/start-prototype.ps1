Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root "frontend"
$cache = Join-Path $root ".install-cache"

$env:npm_config_cache = Join-Path $cache "npm"
New-Item -ItemType Directory -Force -Path $env:npm_config_cache | Out-Null

Push-Location $frontend
try {
  npm run desktop
} finally {
  Pop-Location
}
