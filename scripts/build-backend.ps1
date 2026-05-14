# Compile le backend HERMES en backend.exe autonome (PyInstaller).
#
# Sortie : D:\HermesDeps\tooling\backend-build\backend\backend.exe
# (mode onedir — un dossier contenant l'exe et ses .dll).
#
# Le script :
#   1. Active le venv backend
#   2. Installe pyinstaller si absent
#   3. Compile via hermes_entry.spec
#   4. Copie le dossier de sortie sous D: pour respecter l'invariant
#      "rien de lourd sur E:".

$ErrorActionPreference = "Stop"

$Root         = Resolve-Path "$PSScriptRoot\.."
$Backend      = Join-Path $Root "backend"
$Venv         = Join-Path $Backend ".venv\Scripts\Activate.ps1"
$DistDir      = Join-Path $Backend "dist"
$WorkDir      = Join-Path $Backend "build"
$TargetParent = "D:\HermesDeps\tooling\backend-build"

if (-not (Test-Path $Venv)) {
    Write-Host "[FATAL] venv backend introuvable : $Venv" -ForegroundColor Red
    exit 1
}

. $Venv

# 1. PyInstaller installe si absent
python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> Installation PyInstaller..." -ForegroundColor Cyan
    pip install pyinstaller==6.11.1 | Out-Host
}

# 2. Build
Push-Location $Backend
try {
    Write-Host "==> Compilation backend (PyInstaller, peut prendre 1-2 min)..." -ForegroundColor Cyan
    pyinstaller hermes_entry.spec --noconfirm --distpath $DistDir --workpath $WorkDir
} finally {
    Pop-Location
}

# 3. Deploiement sur D:
$Source = Join-Path $DistDir "backend"
if (-not (Test-Path $Source)) {
    Write-Host "[FATAL] Compilation a echoue : $Source absent" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $TargetParent)) {
    New-Item -ItemType Directory -Path $TargetParent -Force | Out-Null
}

$Target = Join-Path $TargetParent "backend"
if (Test-Path $Target) {
    Write-Host "==> Nettoyage du build precedent..." -ForegroundColor DarkGray
    Remove-Item $Target -Recurse -Force
}

Write-Host "==> Deploiement vers $Target..." -ForegroundColor Cyan
Copy-Item $Source -Destination $TargetParent -Recurse -Force

$Exe = Join-Path $Target "backend.exe"
if (Test-Path $Exe) {
    $size = (Get-ChildItem $Target -Recurse | Measure-Object -Property Length -Sum).Sum
    Write-Host "==> backend.exe pret : $Exe" -ForegroundColor Green
    Write-Host "    Taille totale du bundle : $([math]::Round($size/1MB,1)) Mo" -ForegroundColor DarkGray
} else {
    Write-Host "[FATAL] backend.exe absent dans $Target" -ForegroundColor Red
    exit 1
}
