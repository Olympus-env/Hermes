# Propage une version unique à tous les fichiers qui la déclarent.
#
# La version de HERMES vit dans 6 endroits (contrainte des outils : npm, Cargo,
# Tauri, PyInstaller/Inno Setup ne partagent pas de source commune). Ce script
# évite les désynchronisations — typiquement HERMES.iss oublié, qui produit un
# installeur mal nommé.
#
# Usage :
#   .\scripts\sync-version.ps1 1.0.2
#   .\scripts\sync-version.ps1 -Check        # vérifie la cohérence sans écrire

param(
    [Parameter(Position = 0)]
    [string]$Version,
    [switch]$Check
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path "$PSScriptRoot\.."

# (chemin, regex anchored, gabarit de remplacement)
$Cibles = @(
    @{ Path = "backend\hermes\__init__.py";           Pattern = '(?m)^__version__ = "[^"]*"';        Format = '__version__ = "{0}"' },
    @{ Path = "backend\pyproject.toml";                Pattern = '(?m)^version = "[^"]*"';             Format = 'version = "{0}"' },
    @{ Path = "frontend\package.json";                 Pattern = '"version": "[^"]*"';                 Format = '"version": "{0}"' },
    @{ Path = "frontend\src-tauri\tauri.conf.json";    Pattern = '"version": "[^"]*"';                 Format = '"version": "{0}"' },
    @{ Path = "frontend\src-tauri\Cargo.toml";         Pattern = '(?m)^version = "[^"]*"';             Format = 'version = "{0}"' },
    @{ Path = "installer\HERMES.iss";                  Pattern = '#define MyAppVersion "[^"]*"';       Format = '#define MyAppVersion "{0}"' }
)

function Get-CurrentVersion([string]$content, [string]$pattern) {
    $m = [regex]::Match($content, $pattern)
    if (-not $m.Success) { return $null }
    $v = [regex]::Match($m.Value, '\d+\.\d+\.\d+')
    return $v.Value
}

if ($Check) {
    $versions = @{}
    foreach ($c in $Cibles) {
        $full = Join-Path $Root $c.Path
        $content = Get-Content $full -Raw
        $v = Get-CurrentVersion $content $c.Pattern
        Write-Host ("  {0,-40} {1}" -f $c.Path, $v)
        $versions[$v] = $true
    }
    if ($versions.Keys.Count -eq 1) {
        Write-Host "==> Versions cohérentes : $($versions.Keys)" -ForegroundColor Green
        exit 0
    }
    Write-Host "[FATAL] Versions désynchronisées." -ForegroundColor Red
    exit 1
}

if (-not $Version) {
    Write-Host "Usage : .\scripts\sync-version.ps1 <version>  |  -Check" -ForegroundColor Yellow
    exit 1
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    Write-Host "[FATAL] Version invalide : '$Version' (attendu X.Y.Z)" -ForegroundColor Red
    exit 1
}

foreach ($c in $Cibles) {
    $full = Join-Path $Root $c.Path
    $content = Get-Content $full -Raw
    $remplacement = $c.Format -f $Version
    $nouveau = [regex]::Replace($content, $c.Pattern, $remplacement, 1)
    if ($nouveau -ne $content) {
        Set-Content -Path $full -Value $nouveau -NoNewline
        Write-Host "  mis à jour : $($c.Path) -> $Version" -ForegroundColor Cyan
    } else {
        Write-Host "  inchangé   : $($c.Path)" -ForegroundColor DarkGray
    }
}
Write-Host "==> Version $Version propagée. Pense à 'cargo build' pour rafraîchir Cargo.lock." -ForegroundColor Green
