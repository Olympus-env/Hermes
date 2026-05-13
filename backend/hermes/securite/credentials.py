"""Chiffrement local des identifiants de portails privés.

Les credentials ARGOS sont stockés en base uniquement sous forme chiffrée.
Le format est volontairement simple et versionné :

    b"HERMES-AESGCM-v1" + nonce(12 octets) + ciphertext

La clé maître est lue depuis `HERMES_MASTER_KEY` si fourni, sinon générée une
fois dans `data/master.key` (ignoré par Git).
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from hermes.config import settings

_PREFIX = b"HERMES-AESGCM-v1"
_NONCE_SIZE = 12
_KEY_SIZE = 32


class ErreurCredentials(ValueError):
    """Erreur de lecture, format ou déchiffrement des credentials."""


def chiffrer_credentials(credentials: dict[str, str]) -> bytes:
    """Chiffre un dictionnaire d'identifiants avec AES-256-GCM."""
    _valider_credentials(credentials)
    key = _charger_cle_maitre()
    nonce = os.urandom(_NONCE_SIZE)
    payload = json.dumps(credentials, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, payload, associated_data=_PREFIX)
    return _PREFIX + nonce + ciphertext


def dechiffrer_credentials(blob: bytes | None) -> dict[str, str] | None:
    """Déchiffre des credentials stockés en base."""
    if blob is None:
        return None
    if not blob.startswith(_PREFIX) or len(blob) <= len(_PREFIX) + _NONCE_SIZE:
        raise ErreurCredentials("Format de credentials chiffrés invalide")

    key = _charger_cle_maitre()
    offset = len(_PREFIX)
    nonce = blob[offset : offset + _NONCE_SIZE]
    ciphertext = blob[offset + _NONCE_SIZE :]
    try:
        payload = AESGCM(key).decrypt(nonce, ciphertext, associated_data=_PREFIX)
        data = json.loads(payload.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ErreurCredentials("Impossible de déchiffrer les credentials") from exc

    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise ErreurCredentials("Payload credentials invalide")
    return data


def _charger_cle_maitre() -> bytes:
    if settings.master_key:
        return _normaliser_cle(settings.master_key)
    return _charger_ou_generer_cle_fichier(settings.master_key_path)


def _charger_ou_generer_cle_fichier(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return _normaliser_cle(path.read_text(encoding="utf-8").strip())

    key = os.urandom(_KEY_SIZE)
    path.write_text(base64.urlsafe_b64encode(key).decode("ascii"), encoding="utf-8")
    return key


def _normaliser_cle(valeur: str) -> bytes:
    brute = valeur.strip()
    try:
        key = base64.urlsafe_b64decode(_padding_base64(brute))
    except Exception as exc:  # noqa: BLE001
        raise ErreurCredentials("Clé maître invalide : base64 attendu") from exc
    if len(key) != _KEY_SIZE:
        raise ErreurCredentials("Clé maître invalide : 32 octets requis")
    return key


def _padding_base64(valeur: str) -> str:
    return valeur + "=" * (-len(valeur) % 4)


def _valider_credentials(credentials: dict[str, Any]) -> None:
    if not credentials:
        raise ErreurCredentials("Credentials vides")
    if not all(isinstance(k, str) and k.strip() for k in credentials):
        raise ErreurCredentials("Toutes les clés de credentials doivent être non vides")
    if not all(isinstance(v, str) for v in credentials.values()):
        raise ErreurCredentials("Toutes les valeurs de credentials doivent être des chaînes")
