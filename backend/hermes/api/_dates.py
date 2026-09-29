"""Sérialisation des datetimes en UTC explicite (suffixe Z / +00:00).

SQLite relit les datetimes sans fuseau : sans suffixe, le frontend
(`new Date(iso)`) les interprète en heure locale et décale l'affichage.
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import PlainSerializer


def en_utc_iso(valeur: datetime) -> str:
    if valeur.tzinfo is None:
        valeur = valeur.replace(tzinfo=UTC)
    return valeur.astimezone(UTC).isoformat()


DatetimeUTC = Annotated[
    datetime, PlainSerializer(en_utc_iso, return_type=str, when_used="json")
]
