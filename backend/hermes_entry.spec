# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — produit backend.exe pour HERMES.

À lancer depuis backend/ :
    pyinstaller hermes_entry.spec --noconfirm

Le binaire résultat se trouve dans `dist/backend/backend.exe` (mode onedir).
"""

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Modules dont PyInstaller a du mal à détecter les imports dynamiques.
hiddenimports: list[str] = []
hiddenimports += collect_submodules("hermes")
hiddenimports += collect_submodules("sqlmodel")
hiddenimports += collect_submodules("sqlalchemy.dialects.sqlite")
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "pydantic_settings",
    "email_validator",
]

# Playwright nécessite ses navigateurs et n'est pas utilisé au démarrage —
# on l'exclut volontairement du bundle pour rester compact. Le scraping
# portails privés (Phase 3) sera réintégré différemment plus tard.
excludes = [
    "playwright",
    "pytest",
    "pytest_asyncio",
    "alembic",
    "_pytest",
]

a = Analysis(
    ["hermes_entry.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # garde la console — utile pour debug ; passera à False en prod
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="backend",
)
