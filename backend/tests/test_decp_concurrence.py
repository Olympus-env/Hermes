"""DECP (issue #32) : liaison AO ↔ acheteur, cache, analyse et API de concurrence."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from hermes.agents.argos import decp
from hermes.agents.argos.boamp import _record_vers_ao, extraire_identifiants
from hermes.db.models import AppelOffre, CacheDecp, Portail
from hermes.db.session import _migrer_colonnes, get_engine
from hermes.main import app

# --- Extraction SIRET / CPV depuis `donnees` BOAMP --------------------------

EFORMS = {
    "EFORMS": {
        "ContractNotice": {
            "ext:UBLExtensions": {"efac:Organizations": {"efac:Organization": [
                {"efac:Company": {
                    "cac:PartyIdentification": {"cbc:ID": {"#text": "ORG-0000"}},
                    "cac:PartyLegalEntity": {"cbc:CompanyID": "45072478600030"}}},
                {"efac:Company": {
                    "cac:PartyIdentification": {"cbc:ID": {"#text": "ORG-0001"}},
                    "cac:PartyLegalEntity": {"cbc:CompanyID": "20001784600045"}}},
            ]}},
            "cac:ContractingParty": {"cac:Party": {
                "cac:PartyIdentification": {"cbc:ID": "ORG-0001"}}},
            "cac:ProcurementProject": {"cbc:ItemClassificationCode": {
                "@listName": "cpv", "#text": "22113000"}},
        }
    }
}
FNSIMPLE = {"FNSimple": {
    "organisme": {"codeIdentificationNational": "20006973000055"},
    "objet": {"codeCPV": {"objetPrincipal": {"classPrincipale": "45223000"}}},
}}
ANCIEN = {"IDENTITE": {"CODE_IDENT_NATIONAL": "21590271900016"},
          "OBJET": {"CPV": {"PRINCIPAL": "33760000"}}}


@pytest.mark.parametrize(
    ("donnees", "attendu"),
    [
        (EFORMS, ("20001784600045", "22113000")),  # acheteur, pas la plateforme ORG-0000
        (FNSIMPLE, ("20006973000055", "45223000")),
        (ANCIEN, ("21590271900016", "33760000")),
        ({"FNSimple": {"organisme": {"codeIdentificationNational": "123456789"}}}, (None, None)),
        ("pas du json", (None, None)),
        (None, (None, None)),
    ],
)
def test_extraire_identifiants(donnees, attendu):
    if isinstance(donnees, dict):
        donnees = json.dumps(donnees)  # ODS fournit `donnees` en chaîne JSON
    assert extraire_identifiants(donnees) == attendu


def test_record_boamp_porte_siret_et_cpv():
    ao = _record_vers_ao({"idweb": "26-1", "objet": "x", "donnees": json.dumps(FNSIMPLE)})
    assert (ao.emetteur_siret, ao.code_cpv) == ("20006973000055", "45223000")


# --- Migration ----------------------------------------------------------------


def test_migration_ajoute_siret_et_cpv():
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_appels_offre_emetteur_siret"))
        conn.execute(text("ALTER TABLE appels_offre DROP COLUMN emetteur_siret"))
        conn.execute(text("ALTER TABLE appels_offre DROP COLUMN code_cpv"))
    with engine.connect() as conn:
        _migrer_colonnes(conn)
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info('appels_offre')"))}
    assert {"emetteur_siret", "code_cpv"} <= cols


# --- Analyse ---------------------------------------------------------------------

AUJOURDHUI = date(2026, 9, 29)


def _m(uid, titulaire, montant, jours, offres=None, cpv="72600000"):
    return {"uid": uid, "titulaire_id": titulaire, "titulaire_nom": f"Soc {titulaire}",
            "montant": montant, "cpv": cpv, "objet": "o", "offres": offres,
            "date": (AUJOURDHUI - timedelta(days=jours)).isoformat()}


def test_analyse_titulaires_median_tendance():
    marches = [
        _m("a", "T1", 100, 30, 3), _m("b", "T1", 300, 60, 5), _m("c", "T2", 200, 90),
        _m("d", "T2", 100, 500), _m("e", "T3", 100, 600),
        _m("b", "T9", 300, 60, 5),  # co-titulaire du marché b : marché compté une fois
    ]
    r = decp.analyser(marches, aujourdhui=AUJOURDHUI)
    assert r["nb_marches"] == 5
    assert r["montant_median"] == 100
    assert r["offres_moyennes"] == 4
    assert r["titulaires"][0]["siret"] == "T1"
    assert r["titulaires"][0]["nb_marches"] == 2
    t = r["tendance"]
    assert (t["nb_recent"], t["nb_precedent"]) == (3, 2)
    assert t["sens"] == "hausse"  # médiane 200 vs 100


def test_analyse_vide():
    r = decp.analyser([], aujourdhui=AUJOURDHUI)
    assert r["nb_marches"] == 0 and r["montant_median"] is None
    assert r["tendance"]["sens"] == "indeterminee"


# --- Cache ------------------------------------------------------------------------


async def test_cache_ttl_et_panne(monkeypatch):
    appels: list[dict] = []

    async def faux(filtres, depuis):
        appels.append(filtres)
        return [_m("a", "T1", 100, 10)], 1

    monkeypatch.setattr(decp, "_requeter", faux)
    with Session(get_engine()) as s:
        await decp._marches_en_cache(s, "acheteur:1", {"acheteur_id__exact": "1"})
        _, _, _, cache = await decp._marches_en_cache(s, "acheteur:1", {})
        assert cache and len(appels) == 1  # second appel servi par le cache

        ligne = s.exec(select(CacheDecp)).one()
        ligne.recupere_le = datetime.now(UTC) - timedelta(days=2)
        s.add(ligne)
        s.commit()

        async def panne(filtres, depuis):
            raise httpx.ConnectError("hors ligne")

        monkeypatch.setattr(decp, "_requeter", panne)
        marches, _, _, cache = await decp._marches_en_cache(s, "acheteur:1", {})
        assert cache and marches  # cache périmé plutôt que rien

        with pytest.raises(decp.DecpIndisponible):
            await decp._marches_en_cache(s, "acheteur:inconnu", {})


# --- API ------------------------------------------------------------------------------


def _creer_ao(**kw) -> int:
    with Session(get_engine()) as s:
        ao = AppelOffre(url_source="https://x.test/1", titre="AO", **kw)
        s.add(ao)
        s.commit()
        s.refresh(ao)
        return ao.id


def test_api_concurrence(monkeypatch):
    async def faux(filtres, depuis):
        return [_m("a", "T1", 100, 10, 4), _m("b", "T1", 200, 20, 2)], 2

    monkeypatch.setattr(decp, "_requeter", faux)
    ao_id = _creer_ao(emetteur_siret="20006973000055", code_cpv="72600000")
    with TestClient(app) as client:
        r = client.get(f"/appels-offre/{ao_id}/concurrence")
    assert r.status_code == 200
    j = r.json()
    assert j["acheteur"]["nb_marches"] == 2
    assert j["acheteur"]["titulaires"][0]["nb_marches"] == 2
    assert j["secteur"]["nb_marches"] == 2
    assert j["message"] is None


def test_api_concurrence_sans_identifiants():
    ao_id = _creer_ao()
    with TestClient(app) as client:
        r = client.get(f"/appels-offre/{ao_id}/concurrence")
    assert r.status_code == 200
    assert r.json()["acheteur"] is None and "non calculable" in r.json()["message"]


def test_api_concurrence_source_en_panne(monkeypatch):
    async def panne(filtres, depuis):
        raise httpx.ConnectError("hors ligne")

    monkeypatch.setattr(decp, "_requeter", panne)
    ao_id = _creer_ao(emetteur_siret="20006973000055")
    with TestClient(app) as client:
        r = client.get(f"/appels-offre/{ao_id}/concurrence")
    assert r.status_code == 200
    assert r.json()["acheteur"] is None and "indisponible" in r.json()["message"]


def test_api_concurrence_404():
    with TestClient(app) as client:
        assert client.get("/appels-offre/999/concurrence").status_code == 404


def test_api_rattrapage_siret_boamp(monkeypatch):
    from hermes.api import concurrence as api

    async def faux_rattrapage(idweb):
        return "20006973000055", "72600000"

    async def faux(filtres, depuis):
        return [_m("a", "T1", 100, 10)], 1

    monkeypatch.setattr(api, "recuperer_identifiants", faux_rattrapage)
    monkeypatch.setattr(decp, "_requeter", faux)
    with Session(get_engine()) as s:
        p = Portail(nom="boamp", url_base="https://www.boamp.fr")
        s.add(p)
        s.commit()
        s.refresh(p)
        pid = p.id
    ao_id = _creer_ao(portail_id=pid, reference_externe="26-1")
    with TestClient(app) as client:
        assert client.get(f"/appels-offre/{ao_id}/concurrence").json()["acheteur"] is not None
    with Session(get_engine()) as s:
        assert s.get(AppelOffre, ao_id).emetteur_siret == "20006973000055"


def test_api_concurrence_requetes_paralleles(monkeypatch):
    """3 GET simultanés sur un AO frais : 3×200 et une seule série de requêtes réseau."""
    import asyncio

    appels: list[dict] = []

    async def lent(filtres, depuis):
        appels.append(filtres)
        await asyncio.sleep(0.2)
        return [_m("a", "T1", 100, 10)], 1

    monkeypatch.setattr(decp, "_requeter", lent)
    ao_id = _creer_ao(emetteur_siret="20006973000055")

    async def lancer():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1",
        ) as c:
            return await asyncio.gather(
                *[c.get(f"/appels-offre/{ao_id}/concurrence") for _ in range(3)]
            )

    reponses = asyncio.run(lancer())
    assert [r.status_code for r in reponses] == [200, 200, 200]
    assert all(r.json()["acheteur"]["nb_marches"] == 1 for r in reponses)
    assert len(appels) == 1
    with Session(get_engine()) as s:
        assert len(s.exec(select(CacheDecp)).all()) == 1


def test_echantillon_plafonne_sur_lignes_brutes(monkeypatch):
    """Le plafond se juge avant le filtre de préfixe CPV ; période et total exposés."""
    n = decp.TAILLE_PAGE * decp.MAX_PAGES
    brut = [_m(f"u{i}", "T1", 100, 10 + i, cpv="77310000" if i % 2 else "01000000")
            for i in range(n)]  # ~600 jours couverts seulement

    async def faux(filtres, depuis):
        return brut, 10022

    monkeypatch.setattr(decp, "_requeter", faux)
    ao_id = _creer_ao(code_cpv="77310000")
    with TestClient(app) as client:
        j = client.get(f"/appels-offre/{ao_id}/concurrence").json()
    s = j["secteur"]
    assert s["nb_marches"] == n // 2 < n  # le filtre réduit le nombre affiché
    assert s["echantillon_plafonne"] is True
    assert s["total_reel"] == 10022
    assert s["periode_debut"] and s["periode_fin"]
    assert s["tendance"]["precedent_couvert"] is False
    assert s["tendance"]["sens"] == "indeterminee"


def test_rattrapage_boamp_cache_negatif(monkeypatch):
    from hermes.api import concurrence as api

    appels = []

    async def vide(idweb):
        appels.append(idweb)
        return None, None

    api._rattrapages_vides.clear()
    monkeypatch.setattr(api, "recuperer_identifiants", vide)
    with Session(get_engine()) as s:
        p = Portail(nom="boamp", url_base="https://www.boamp.fr")
        s.add(p)
        s.commit()
        s.refresh(p)
        pid = p.id
    ao_id = _creer_ao(portail_id=pid, reference_externe="26-2")
    with TestClient(app) as client:
        client.get(f"/appels-offre/{ao_id}/concurrence")
        client.get(f"/appels-offre/{ao_id}/concurrence")
    assert len(appels) == 1
