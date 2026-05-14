"""Point d'entrée HERMES pour PyInstaller — produit backend.exe autonome.

PyInstaller a besoin d'un script unique invoqué directement, et non d'un
appel `python -m uvicorn …`. Ce wrapper démarre uvicorn programmatiquement
en chargeant l'application FastAPI via son chemin d'import.

Le binaire généré écoute sur 127.0.0.1:8000 et lit ses paramètres via
les variables d'environnement HERMES_* habituelles.
"""

from __future__ import annotations

import os
import sys

import uvicorn

# Import explicite — sans ça, PyInstaller ne suit pas la string "hermes.main:app"
# passée à uvicorn et le module est introuvable dans le bundle frozen.
from hermes.main import app


def main() -> None:
    host = os.environ.get("HERMES_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("HERMES_PORT", "8000"))
    except ValueError:
        port = 8000

    # En mode bundle PyInstaller, on désactive le reload (incompatible avec
    # le frozen binary) et on passe l'objet `app` directement (pas une string)
    # pour éviter un nouvel import dynamique qui échouerait.
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=False,
        workers=1,
        log_level=os.environ.get("HERMES_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    sys.exit(main() or 0)
