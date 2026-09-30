"""Tests KRINOS — consommation Jev par jour/mois et estimation en € (issue #43)."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from hermes.agents.krinos import jev
from hermes.config import settings
from hermes.db.models import Parametre
from hermes.db.session import get_engine, init_db
from hermes.main import app


def _remise_a_zero() -> None:
    init_db()
    with Session(get_engine()) as s:
        p = s.get(Parametre, jev.CLE_BUDGET)
        if p is not None:
            s.delete(p)
            s.commit()


def test_compteurs_jour_mois_reserver_regulariser():
    _remise_a_zero()
    with Session(get_engine()) as s:
        jev._reserver(s, 1000)
        assert (jev.tokens_consommes(s), jev.tokens_consommes_jour(s)) == (1000, 1000)
        jev._regulariser(s, 1000, 760)
        assert (jev.tokens_consommes(s), jev.tokens_consommes_jour(s)) == (760, 760)
        jev._regulariser(s, 0, 0)


def test_jour_repart_a_zero_pas_le_mois(monkeypatch):
    _remise_a_zero()
    with Session(get_engine()) as s:
        jev._reserver(s, 500)
        monkeypatch.setattr(jev, "_jour_courant", lambda: "1999-01-01")
        assert jev.tokens_consommes_jour(s) == 0
        assert jev.tokens_consommes(s) == 500


def test_api_sans_tarif_pas_d_estimation(monkeypatch):
    monkeypatch.setattr(settings, "jev_prix_eur_par_mtokens", None)
    monkeypatch.setattr(settings, "jev_budget_tokens_mois", 2_000_000)
    _remise_a_zero()
    with Session(get_engine()) as s:
        jev._reserver(s, 200_000)
    with TestClient(app) as client:
        data = client.get("/krinos/jev").json()
    assert data["tokens_consommes_jour"] == 200_000
    assert data["tokens_restants"] == 1_800_000
    assert data["pourcentage_budget"] == 10.0
    assert data["cout_estime_mois_eur"] is None
    assert data["cout_estime_jour_eur"] is None


def test_api_avec_tarif_estime_en_euros(monkeypatch):
    monkeypatch.setattr(settings, "jev_prix_eur_par_mtokens", 2.5)
    _remise_a_zero()
    with Session(get_engine()) as s:
        jev._reserver(s, 400_000)
    with TestClient(app) as client:
        data = client.get("/krinos/jev").json()
    assert data["cout_estime_mois_eur"] == 1.0
    assert data["cout_estime_jour_eur"] == 1.0
    assert data["prix_eur_par_mtokens"] == 2.5
