# Lance HERMES (PYTHIA + backend + desktop) avec gestion du cycle de vie.
#
# Au demarrage : verifie qu'aucune instance HERMES n'est deja en cours
# (sinon les tue), puis lance dans l'ordre PYTHIA, le backend Python,
# l'application desktop Tauri.
#
# A la fermeture de l'application desktop, kill automatiquement le backend
# et Ollama (si demarres par ce script). C'est l'equivalent PowerShell du
# launcher .exe -- utilisable immediatement sans .NET SDK.

$ErrorActionPreference = "Stop"

$Root        = Resolve-Path "$PSScriptRoot\.."
$Backend     = Join-Path $Root "backend"
$Python      = Join-Path $Backend ".venv\Scripts\python.exe"
$DepsDir     = "D:\HermesDeps"
$Ollama      = Join-Path $DepsDir "ollama\bin\ollama.exe"
$Desktop     = Join-Path $DepsDir "tooling\cargo-target\release\hermes.exe"

function Test-Required {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path $Path)) {
        Write-Host "[FATAL] $Label introuvable : $Path" -ForegroundColor Red
        exit 1
    }
}

function Test-Healthy {
    param([string]$Url, [int]$TimeoutSec = 2)
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Wait-Healthy {
    param([string]$Url, [int]$TimeoutSec = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Healthy -Url $Url -TimeoutSec 2) { return $true }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

function Stop-MatchingProcess {
    param([string]$Pattern)
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match $Pattern } | ForEach-Object {
        try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch { }
    }
}

# --- 0. Sanity checks ------------------------------------------------------
Test-Required -Path $Python  -Label "Python venv backend"
Test-Required -Path $Ollama  -Label "Ollama/PYTHIA"
Test-Required -Path $Desktop -Label "Application desktop HERMES"

# --- 1. Nettoyage des zombies eventuels -----------------------------------
Write-Host "==> Nettoyage des processus HERMES preexistants..." -ForegroundColor Cyan
Stop-MatchingProcess -Pattern "uvicorn hermes\.main"
Stop-MatchingProcess -Pattern "hermes\.exe"
# Ollama : on ne tue PAS s'il tournait deja, on le laissera tel quel a la fin.
$ollamaPreexistant = Test-Healthy -Url "http://127.0.0.1:11434/api/tags"

# --- 2. PYTHIA / Ollama ----------------------------------------------------
$ollamaProc = $null
if ($ollamaPreexistant) {
    Write-Host "==> PYTHIA deja en route, on le reutilise." -ForegroundColor DarkGray
} else {
    Write-Host "==> Demarrage PYTHIA/Ollama..." -ForegroundColor Cyan
    $env:OLLAMA_MODELS = Join-Path $DepsDir "ollama\models"
    $ollamaProc = Start-Process -FilePath $Ollama -ArgumentList "serve" `
        -WindowStyle Hidden -PassThru
    if (-not (Wait-Healthy -Url "http://127.0.0.1:11434/api/tags" -TimeoutSec 25)) {
        Write-Host "[FATAL] PYTHIA n'a pas repondu sur 11434." -ForegroundColor Red
        if ($ollamaProc) { Stop-Process -Id $ollamaProc.Id -Force }
        exit 1
    }
    Write-Host "    PYTHIA pret (PID $($ollamaProc.Id))" -ForegroundColor Green
}

# --- 3. Backend FastAPI ----------------------------------------------------
Write-Host "==> Demarrage backend HERMES..." -ForegroundColor Cyan
$env:HERMES_DB_PATH      = Join-Path $Root "data\hermes.db"
$env:HERMES_STORAGE_PATH = Join-Path $Root "data\storage"
$env:HERMES_LOG_PATH     = Join-Path $Root "data\logs"
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $DepsDir "tooling\ms-playwright"

$backendProc = Start-Process -FilePath $Python -ArgumentList @(
    "-m", "uvicorn", "hermes.main:app",
    "--host", "127.0.0.1", "--port", "8000"
) -WorkingDirectory $Backend -WindowStyle Hidden -PassThru
if (-not (Wait-Healthy -Url "http://127.0.0.1:8000/health" -TimeoutSec 35)) {
    Write-Host "[FATAL] Backend HERMES n'a pas repondu sur 8000." -ForegroundColor Red
    Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
    if ($ollamaProc) { Stop-Process -Id $ollamaProc.Id -Force -ErrorAction SilentlyContinue }
    exit 1
}
Write-Host "    Backend pret (PID $($backendProc.Id))" -ForegroundColor Green

# --- 4. Desktop Tauri + attente fermeture ---------------------------------
Write-Host "==> Lancement de l'application HERMES..." -ForegroundColor Cyan
$desktopProc = Start-Process -FilePath $Desktop -PassThru
Write-Host "    HERMES en cours d'execution (PID $($desktopProc.Id))." -ForegroundColor Green
Write-Host "    Fermer la fenetre arretera automatiquement backend + PYTHIA." -ForegroundColor DarkGray

# Bloque jusqu'a la fermeture de la fenetre Tauri.
try {
    $desktopProc.WaitForExit()
} finally {
    Write-Host "==> Arret du backend HERMES..." -ForegroundColor Cyan
    Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
    if ($ollamaProc) {
        Write-Host "==> Arret de PYTHIA (demarre par ce script)..." -ForegroundColor Cyan
        Stop-Process -Id $ollamaProc.Id -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "    PYTHIA preexistant laisse en route." -ForegroundColor DarkGray
    }
    Write-Host "==> HERMES termine proprement." -ForegroundColor Yellow
}
