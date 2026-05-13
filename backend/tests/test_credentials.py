"""Tests du chiffrement local des credentials ARGOS."""

from __future__ import annotations

import base64
import os

import pytest

from hermes.config import settings
from hermes.securite.credentials import (
    ErreurCredentials,
    chiffrer_credentials,
    dechiffrer_credentials,
)


def test_credentials_chiffres_dechiffres(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "master_key", None)
    monkeypatch.setattr(settings, "master_key_path", tmp_path / "master.key")

    blob = chiffrer_credentials({"login": "demo", "password": "secret"})

    assert b"secret" not in blob
    assert dechiffrer_credentials(blob) == {"login": "demo", "password": "secret"}
    assert (tmp_path / "master.key").exists()


def test_credentials_refuse_payload_vide(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "master_key", None)
    monkeypatch.setattr(settings, "master_key_path", tmp_path / "master.key")

    with pytest.raises(ErreurCredentials):
        chiffrer_credentials({})


def test_credentials_supporte_cle_env(monkeypatch, tmp_path):
    key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setattr(settings, "master_key", key)
    monkeypatch.setattr(settings, "master_key_path", tmp_path / "master.key")

    blob = chiffrer_credentials({"token": "abc"})

    assert dechiffrer_credentials(blob) == {"token": "abc"}
    assert not (tmp_path / "master.key").exists()
