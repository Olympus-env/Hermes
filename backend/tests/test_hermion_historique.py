"""Issue #77 — tri par échéance d'AO et règle d'historique des versions."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from hermes.db.models import AppelOffre, ReponseHermion, StatutReponse
from hermes.db.session import get_engine
from hermes.main import app


def _ao(titre, date_limite=None) -> int:
    with Session(get_engine()) as s:
        ao = AppelOffre(url_source=f"http://x/{titre}", titre=titre, date_limite=date_limite)
        s.add(ao)
        s.commit()
        return ao.id


def _rep(ao_id, version, statut=StatutReponse.EN_ATTENTE) -> int:
    with Session(get_engine()) as s:
        r = ReponseHermion(
            appel_offre_id=ao_id, version=version, contenu="texte", statut=statut
        )
        s.add(r)
        s.commit()
        return r.id


def test_liste_triee_par_echeance_puis_version_decroissante():
    maintenant = datetime.now(UTC)
    ao_tard = _ao("tard", maintenant + timedelta(days=20))
    ao_sans = _ao("sans-date")
    ao_tot = _ao("tot", maintenant + timedelta(days=2))
    _rep(ao_tard, 1)
    _rep(ao_sans, 1)
    _rep(ao_tot, 1)
    _rep(ao_tot, 2)
    _rep(ao_tard, 2)

    with TestClient(app) as client:
        lignes = client.get("/hermion/reponses").json()

    ordre = [(ligne["appel_offre_titre"], ligne["version"]) for ligne in lignes]
    assert ordre == [("tot", 2), ("tot", 1), ("tard", 2), ("tard", 1), ("sans-date", 1)]
    assert lignes[0]["appel_offre_date_limite"] is not None
    assert lignes[-1]["appel_offre_date_limite"] is None


def test_historique_expose_commentaire():
    ao_id = _ao("hist")
    rep_id = _rep(ao_id, 1)
    with TestClient(app) as client:
        client.patch(
            f"/hermion/reponses/{rep_id}/statut",
            json={"statut": "a_modifier", "commentaire_humain": "à reprendre"},
        )
        versions = client.get(f"/hermion/appels-offre/{ao_id}/reponses").json()
    assert versions[0]["commentaire_humain"] == "à reprendre"


def test_ancienne_version_non_validable_si_plus_recente():
    ao_id = _ao("regle")
    v1 = _rep(ao_id, 1)
    v2 = _rep(ao_id, 2)
    with TestClient(app) as client:
        r = client.patch(f"/hermion/reponses/{v1}/statut", json={"statut": "validee"})
        assert r.status_code == 409
        assert "v2" in r.json()["detail"]
        # La dernière version reste validable.
        assert (
            client.patch(f"/hermion/reponses/{v2}/statut", json={"statut": "validee"}).status_code
            == 200
        )


def test_ancienne_version_validable_si_plus_recente_rejetee():
    ao_id = _ao("regle-rejet")
    v1 = _rep(ao_id, 1)
    _rep(ao_id, 2, StatutReponse.REJETEE)
    with TestClient(app) as client:
        r = client.patch(f"/hermion/reponses/{v1}/statut", json={"statut": "validee"})
    assert r.status_code == 200
