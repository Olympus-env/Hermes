"""Tests du parseur TED (offline, snapshot statique du JSON Search API v3)."""

from __future__ import annotations

from hermes.agents.argos.ted import (
    _est_valide,
    _notice_vers_ao,
    _parse_date,
    _premier_lien,
    _texte_multi,
)

# Échantillon représentatif des formes eForms observées : titre multilingue
# en objet indexé par langue, buyer-name en liste, links html/pdf par langue.
_SNAPSHOT = [
    {
        "publication-number": "123456-2026",
        "notice-title": {
            "fra": "Marché de maintenance applicative du SI métier",
            "eng": "Application maintenance contract",
        },
        "publication-date": "2026-05-12+02:00",
        "buyer-name": {"fra": ["Ministère de l'Intérieur"]},
        "place-of-performance": ["FRA", "FRA"],
        "classification-cpv": ["72000000", "72500000"],
        "links": {
            "html": {"FRA": "https://ted.europa.eu/fr/notice/-/detail/123456-2026"},
            "pdf": {"FRA": "https://ted.europa.eu/fr/notice/123456-2026/pdf"},
        },
    },
    {
        "publication-number": "999000-2026",
        # Titre sous forme de simple chaîne (autre forme tolérée).
        "notice-title": "Fourniture de serveurs",
        "publication-date": "2026-05-13",
        "buyer-name": "Région Bretagne",
        "place-of-performance": "FRA",
        "links": {},
    },
    {
        # Notice dégénérée : ni titre ni acheteur ⇒ filtrée.
        "publication-number": "000111-2026",
    },
]


def test_filtrage_notices_invalides():
    valides = [n for n in _SNAPSHOT if _est_valide(n)]
    assert len(valides) == 2


def test_conversion_titre_multilingue_prefere_francais():
    ao = _notice_vers_ao(_SNAPSHOT[0])
    assert ao.titre == "Marché de maintenance applicative du SI métier"
    assert ao.reference_externe == "123456-2026"
    assert ao.emetteur == "Ministère de l'Intérieur"
    assert ao.code_naf == "72000000"
    assert ao.zone_geographique == "FRA"  # dédupliqué
    assert ao.url_source.startswith("https://ted.europa.eu/fr/notice")


def test_conversion_titre_chaine_simple():
    ao = _notice_vers_ao(_SNAPSHOT[1])
    assert ao.titre == "Fourniture de serveurs"
    assert ao.emetteur == "Région Bretagne"
    # links vide ⇒ URL de détail reconstruite depuis la référence.
    assert ao.url_source == "https://ted.europa.eu/en/notice/-/detail/999000-2026"


def test_dates_parsees():
    ao = _notice_vers_ao(_SNAPSHOT[0])
    assert ao.date_publication is not None
    assert ao.date_publication.year == 2026
    assert ao.date_publication.month == 5
    # eForms ne fournit pas de date limite fiable ⇒ None assumé.
    assert ao.date_limite is None


def test_parse_date_tolere_offset_et_date_seule():
    assert _parse_date("2026-05-12+02:00") is not None
    assert _parse_date("2026-05-12") is not None
    assert _parse_date("") is None
    assert _parse_date("pas-une-date") is None


def test_texte_multi_formes():
    assert _texte_multi("x ") == "x"
    assert _texte_multi(["", "a", "b"]) == "a"
    assert _texte_multi({"eng": "E", "fra": "F"}) == "F"
    assert _texte_multi({"deu": "D"}) == "D"  # fallback : n'importe quelle langue
    assert _texte_multi(None) is None


def test_premier_lien_priorise_html_puis_pdf():
    assert _premier_lien(
        {"pdf": {"FRA": "https://x/pdf"}, "html": {"ENG": "https://x/html"}}
    ) == "https://x/html"
    assert _premier_lien({"pdf": {"FRA": "https://x/pdf"}}) == "https://x/pdf"
    assert _premier_lien({}) is None


def test_cle_unicite_prefere_reference():
    ao = _notice_vers_ao(_SNAPSHOT[0])
    assert ao.cle_unicite() == "123456-2026"


def test_titre_tronque_si_long():
    notice = {"publication-number": "x", "notice-title": "A" * 800}
    ao = _notice_vers_ao(notice)
    assert len(ao.titre) <= 500
