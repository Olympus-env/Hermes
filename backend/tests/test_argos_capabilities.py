"""Tests des profils de capacités ARGOS (P1) et de leur exposition API."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from hermes.agents.argos import boamp
from hermes.agents.argos.boamp import BoampScraper, _record_vers_ao
from hermes.agents.argos.capabilities import (
    CHAMPS_BOAMP,
    CHAMPS_TED,
    PROFIL_BOAMP,
    PROFIL_TED,
    profil_pour,
    tous_les_profils,
)
from hermes.agents.argos.registry import scrapers_disponibles
from hermes.agents.argos.ted import _FIELDS, TedScraper


def test_profil_pour_connu_et_inconnu():
    assert profil_pour("boamp") is PROFIL_BOAMP
    assert profil_pour("ted") is PROFIL_TED
    assert profil_pour("inexistant") is None


def test_tous_les_profils_couvre_les_scrapers_enregistres():
    portails_profils = {p.portail for p in tous_les_profils()}
    assert set(scrapers_disponibles()) <= portails_profils


def test_scrapers_exposent_leur_profil():
    assert BoampScraper.capacites is PROFIL_BOAMP
    assert TedScraper.capacites is PROFIL_TED


def test_select_boamp_reflete_les_champs_versionnes():
    assert boamp._SELECT == ",".join(CHAMPS_BOAMP)


def test_fields_ted_reflete_les_champs_versionnes():
    assert _FIELDS == list(CHAMPS_TED)


def test_select_boamp_couvre_les_champs_lus_par_le_parseur():
    """`select` ne doit masquer aucun champ exploité par le parseur BOAMP.

    Garde-fou : si quelqu'un ajoute `rec.get("nouveau_champ")` au parseur sans
    l'ajouter à CHAMPS_BOAMP, l'API ne renverrait plus ce champ. On vérifie ici
    que tous les `rec.get("...")` du parseur sont couverts (sauf `titre_marche`,
    repli mort documenté : champ absent du dataset).
    """
    import inspect

    source = inspect.getsource(_record_vers_ao)
    champs_lus = set(re.findall(r"""rec\.get\(["']([\w-]+)["']\)""", source))
    champs_lus.discard("titre_marche")  # repli volontairement non sélectionné
    manquants = champs_lus - set(CHAMPS_BOAMP)
    assert not manquants, f"Champs lus mais absents du select : {manquants}"


def test_endpoint_capacites_renvoie_les_profils():
    from hermes.main import app

    with TestClient(app) as client:
        r = client.get("/argos/capacites")
    assert r.status_code == 200
    data = r.json()
    portails = {item["portail"] for item in data}
    assert {"boamp", "ted"} <= portails

    ted = next(item for item in data if item["portail"] == "ted")
    assert ted["liens_documents"] is True
    assert ted["pagination"] is True
    assert "notice-title" in ted["champs_filtrables"]
