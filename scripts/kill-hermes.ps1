# Tue les processus HERMES zombies (backend uvicorn + Ollama demarre par HERMES).
#
# Utile quand le launcher a plante ou qu'on a lance le backend manuellement
# avant des modifications de code -- les anciens processus continuent de
# repondre sur :8000/:11434 avec du code obsolete.

$ErrorActionPreference = "SilentlyContinue"

function Stop-MatchingProcess {
    param([string]$Pattern, [string]$Label)
    $procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match $Pattern }
    if (-not $procs) {
        Write-Host "  $Label : aucune instance trouvee" -ForegroundColor DarkGray
        return
    }
    foreach ($p in $procs) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Host "  $Label : PID $($p.ProcessId) tue" -ForegroundColor Green
        } catch {
            Write-Host "  $Label : impossible de tuer PID $($p.ProcessId) ($_)" -ForegroundColor Red
        }
    }
}

Write-Host "Arret des processus HERMES..." -ForegroundColor Yellow
Stop-MatchingProcess -Pattern "uvicorn hermes\.main" -Label "Backend HERMES"
Stop-MatchingProcess -Pattern "ollama\.exe.*serve"   -Label "Ollama/PYTHIA"
Stop-MatchingProcess -Pattern "hermes\.exe"          -Label "Desktop Tauri"
Write-Host "Termine." -ForegroundColor Yellow
