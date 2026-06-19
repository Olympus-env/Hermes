"""Non-régression : faux positifs sur acronymes courts (SMS, RCS).

Le garde-fou client (`FiltreVeille`) matche les acronymes courts en **mot
entier**, pas en sous-chaîne nue : un AO ne doit pas être conservé sur la seule
présence de « rcs » dans « sources » ou « sms » à l'intérieur d'un autre mot,
ni sur la mention légale « RCS Paris » d'un acheteur.
"""

from __future__ import annotations

import pytest

from hermes.agents.argos.base import AOCollecte
from hermes.agents.argos.filtre import FiltreVeille, _contient, _est_acronyme_court


def _ao(titre="", objet=None, emetteur=None) -> AOCollecte:
    return AOCollecte(
        titre=titre,
        url_source=f"https://example.test/{titre.replace(' ', '_')}",
        objet=objet,
        emetteur=emetteur,
    )


@pytest.mark.parametrize(
    "terme,attendu",
    [
        ("sms", True),
        ("rcs", True),
        ("amo", True),
        ("java", True),  # 4 caractères → mot entier
        ("h2", True),
        ("maintenance", False),  # expression métier → sous-chaîne
        ("notification", False),
    ],
)
def test_classement_acronyme_court(terme, attendu):
    assert _est_acronyme_court(terme) is attendu


@pytest.mark.parametrize(
    "cible,terme,attendu",
    [
        ("marche d'envoi de sms de notification", "sms", True),
        ("messagerie smsc industrielle", "sms", False),  # sms dans 'smsc'
        ("transmission de donnees", "sms", False),
        ("rcs paris 123", "rcs", True),  # mot entier (sera filtré par contexte)
        ("appel pour sources ouvertes", "rcs", False),  # 'rcs' dans 'sources'
        ("maintenance applicative", "maintenance", True),  # sous-chaîne souple
    ],
)
def test_contient_mot_entier_vs_souschaine(cible, terme, attendu):
    assert _contient(cible, terme) is attendu


def test_filtre_acronyme_sms_match_mot_entier():
    filtre = FiltreVeille(inclus=("SMS",))
    assert filtre.correspond(_ao(titre="Marché d'envoi de SMS")) is True
    # 'SMS' présent uniquement à l'intérieur d'un autre mot → rejeté.
    assert filtre.correspond(_ao(titre="Refonte SMSC télécom")) is False


def test_filtre_acronyme_rcs_ignore_mention_legale_interne():
    filtre = FiltreVeille(inclus=("RCS",))
    # 'rcs' en sous-chaîne de 'sourcing' ne doit pas matcher.
    assert filtre.correspond(_ao(titre="Marché de sourcing fournisseurs")) is False
    # Vrai mot 'RCS' (messagerie enrichie) conservé.
    assert filtre.correspond(_ao(titre="Service RCS et notifications")) is True


def test_filtre_exclus_acronyme_court_en_mot_entier():
    """Un exclus court ne doit pas rejeter sur une sous-chaîne fortuite."""
    filtre = FiltreVeille(inclus=("messagerie",), exclus=("sms",))
    # 'sms' dans 'smsc' ne déclenche pas l'exclusion.
    assert filtre.correspond(_ao(titre="Messagerie SMSC interne")) is True
    # 'sms' mot entier → exclu.
    assert filtre.correspond(_ao(titre="Messagerie et envoi de SMS")) is False
