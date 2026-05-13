"""Tests du parseur BOAMP (offline, snapshot statique de l'API JSON)."""

from __future__ import annotations

from hermes.agents.argos.boamp import _record_vers_ao, _est_valide


_SNAPSHOT = [
    {
        "idweb": "26-12345",
        "id": "26-12345",
        "url_avis": "https://www.boamp.fr/avis/detail/26-12345",
        "objet": "Marché de rénovation énergétique de l'école primaire « Les Tilleuls »",
        "nomacheteur": "Commune de Saint-Étienne",
        "dateparution": "2026-05-12",
        "datelimitereponse": "2026-06-15T17:00:00+00:00",
        "nature_libelle": "Travaux",
        "code_departement": "42",
        "descripteur_code": ["45000000"],
    },
    {
        "idweb": "26-67890",
        "id": "26-67890",
        "url_avis": "https://www.boamp.fr/avis/detail/26-67890",
        "objet": "Fourniture de matériel informatique — marché à bons de commande",
        "nomacheteur": "Région Auvergne-Rhône-Alpes",
        "dateparution": "2026-05-13",
        "datelimitereponse": "2026-06-30",
        "nature_libelle": "Fournitures",
        "code_departement": ["69", "01"],
    },
    {
        # Record dégénéré — pas d'objet ni de nomacheteur ⇒ doit être filtré.
        "idweb": "26-99999",
        "url_avis": "https://www.boamp.fr/avis/detail/26-99999",
    },
]


def test_filtrage_records_invalides():
    valides = [r for r in _SNAPSHOT if _est_valide(r)]
    assert len(valides) == 2


def test_conversion_basique():
    ao = _record_vers_ao(_SNAPSHOT[0])
    assert ao.reference_externe == "26-12345"
    assert ao.url_source == "https://www.boamp.fr/avis/detail/26-12345"
    assert "rénovation énergétique" in ao.titre
    assert ao.emetteur == "Commune de Saint-Étienne"
    assert ao.type_marche == "Travaux"
    assert ao.code_naf == "45000000"
    assert ao.zone_geographique == "42"


def test_dates_parsees():
    ao = _record_vers_ao(_SNAPSHOT[0])
    assert ao.date_publication is not None
    assert ao.date_publication.year == 2026
    assert ao.date_publication.month == 5
    assert ao.date_limite is not None
    assert ao.date_limite.day == 15


def test_zone_geographique_concatenation():
    ao = _record_vers_ao(_SNAPSHOT[1])
    # Avec liste de départements, on concatène en string CSV.
    assert ao.zone_geographique == "69,01"


def test_cle_unicite_prefere_reference():
    ao = _record_vers_ao(_SNAPSHOT[0])
    assert ao.cle_unicite() == "26-12345"


def test_titre_tronque_si_long():
    long_objet = "A" * 800
    rec = {"idweb": "x", "url_avis": "https://x.test", "objet": long_objet, "nomacheteur": "X"}
    ao = _record_vers_ao(rec)
    assert len(ao.titre) <= 500
