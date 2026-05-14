# Construit l'installeur HERMES-Setup-<version>.exe via Inno Setup.
#
# Pipeline :
#   1. Vérifie qu'Inno Setup est installé
#   2. Recompile hermes.exe (Tauri release) si demandé
#   3. Recompile backend.exe (PyInstaller) si demandé
#   4. Copie les artefacts dans installer/staging/
#   5. Télécharge OllamaSetup.exe si absent (peut être skip via -SkipOllama)
#   6. Lance ISCC sur HERMES.iss
#
# Le résultat sort dans installer/dist/HERMES-Setup-<version>.exe.

param(
    [switch]$SkipFrontend,
    [switch]$SkipBackend,
    [switch]$SkipOllama,
    [string]$OllamaUrl = "https://ollama.com/download/OllamaSetup.exe"
)

$ErrorActionPreference = "Stop"

$Root      = Resolve-Path "$PSScriptRoot\.."
$Frontend  = Join-Path $Root "frontend"
$Installer = Join-Path $Root "installer"
$Staging   = Join-Path $Installer "staging"
$DistDir   = Join-Path $Installer "dist"

# 1. Locate Inno Setup
$IsccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    Write-Host "[FATAL] Inno Setup introuvable." -ForegroundColor Red
    Write-Host "  Telecharge et installe Inno Setup 6 (gratuit) depuis :" -ForegroundColor Yellow
    Write-Host "  https://jrsoftware.org/isdl.php" -ForegroundColor Yellow
    exit 1
}
Write-Host "==> Inno Setup : $Iscc" -ForegroundColor DarkGray

# 2. (Re)compile hermes.exe
$HermesExe = "D:\HermesDeps\tooling\cargo-target\release\hermes.exe"
if (-not $SkipFrontend) {
    Write-Host "==> Compilation hermes.exe (Tauri release, peut prendre 5-10 min)..." -ForegroundColor Cyan
    Push-Location $Frontend
    try {
        npm run tauri build | Out-Host
    } finally {
        Pop-Location
    }
}
if (-not (Test-Path $HermesExe)) {
    Write-Host "[FATAL] hermes.exe absent : $HermesExe" -ForegroundColor Red
    Write-Host "  Relance sans -SkipFrontend." -ForegroundColor Yellow
    exit 1
}

# 3. (Re)compile backend.exe
$BackendDir = "D:\HermesDeps\tooling\backend-build\backend"
if (-not $SkipBackend) {
    Write-Host "==> Compilation backend.exe (PyInstaller)..." -ForegroundColor Cyan
    & "$PSScriptRoot\build-backend.ps1" | Out-Host
}
if (-not (Test-Path (Join-Path $BackendDir "backend.exe"))) {
    Write-Host "[FATAL] backend.exe absent : $BackendDir\backend.exe" -ForegroundColor Red
    Write-Host "  Relance sans -SkipBackend." -ForegroundColor Yellow
    exit 1
}

# 4. Prépare le staging
Write-Host "==> Préparation du staging..." -ForegroundColor Cyan
if (Test-Path $Staging) { Remove-Item $Staging -Recurse -Force }
New-Item -ItemType Directory -Path $Staging -Force | Out-Null

Copy-Item $HermesExe -Destination (Join-Path $Staging "hermes.exe") -Force
Copy-Item $BackendDir -Destination (Join-Path $Staging "backend") -Recurse -Force

# Icone — réutilise celle de Tauri si disponible
$TauriIcon = Join-Path $Frontend "src-tauri\icons\icon.ico"
if (Test-Path $TauriIcon) {
    Copy-Item $TauriIcon -Destination (Join-Path $Staging "hermes.ico") -Force
} else {
    Write-Host "  (pas d'icone trouvee, l'installeur utilisera le defaut)" -ForegroundColor DarkGray
}

# 5. OllamaSetup.exe
$OllamaSetup = Join-Path $Staging "OllamaSetup.exe"
if (-not $SkipOllama) {
    Write-Host "==> Telechargement OllamaSetup.exe ($OllamaUrl)..." -ForegroundColor Cyan
    try {
        Invoke-WebRequest -Uri $OllamaUrl -OutFile $OllamaSetup -UseBasicParsing
        $sz = [math]::Round((Get-Item $OllamaSetup).Length / 1MB, 0)
        Write-Host "    OllamaSetup.exe pret ($sz Mo)" -ForegroundColor Green
    } catch {
        Write-Host "  [WARN] Echec telechargement Ollama : $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "  L'installeur sera genere sans Ollama embarque." -ForegroundColor Yellow
    }
} else {
    Write-Host "==> -SkipOllama : Ollama non bundle (l'utilisateur l'installera manuellement)" -ForegroundColor DarkGray
}

# 6. Compile l'installeur
Write-Host "==> Compilation Inno Setup..." -ForegroundColor Cyan
if (-not (Test-Path $DistDir)) { New-Item -ItemType Directory -Path $DistDir -Force | Out-Null }

Push-Location $Installer
try {
    & $Iscc "HERMES.iss" | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FATAL] ISCC a echoue (code $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}

# 7. Resultat
$Setup = Get-ChildItem $DistDir -Filter "HERMES-Setup-*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($Setup) {
    $sz = [math]::Round($Setup.Length / 1MB, 1)
    Write-Host "==> Installeur pret : $($Setup.FullName) ($sz Mo)" -ForegroundColor Green
} else {
    Write-Host "[FATAL] Installeur introuvable dans $DistDir" -ForegroundColor Red
    exit 1
}
