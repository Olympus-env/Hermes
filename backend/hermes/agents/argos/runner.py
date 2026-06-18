"""Exécution d'une collecte : appel du scraper → persistance MNEMOSYNE → logs."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from loguru import logger
from sqlmodel import Session, select

from hermes.agents.argos.base import AOCollecte, ResultatCollecte, Scraper
from hermes.agents.argos.filtre import charger_filtre
from hermes.db.models import AppelOffre, LogAgent, NiveauLog, Portail, StatutAO
from hermes.securite.credentials import ErreurCredentials, dechiffrer_credentials


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def executer_collecte(
    scraper: Scraper,
    session: Session,
    *,
    limite: int = 20,
) -> ResultatCollecte:
    """Lance un scraper, persiste les nouveaux AO, journalise."""

    debut = time.monotonic()
    resultat = ResultatCollecte(portail=scraper.nom)

    portail = _portail_ou_creer(session, scraper)
    _injecter_credentials(scraper, portail)

    # Charge le filtre une fois : poussé au scraper (filtrage côté API quand le
    # portail le supporte) puis réutilisé pour le garde-fou client ci-dessous.
    filtre = charger_filtre(session)
    _injecter_filtre(scraper, filtre)

    # Fenêtre incrémentale : on pousse la date de la collecte précédente pour
    # que le scraper arrête de paginer une fois la fenêtre dépassée (la valeur
    # courante n'est mise à jour qu'en fin de collecte, plus bas).
    _injecter_fenetre(scraper, portail)

    try:
        items = await scraper.collecter(limite=limite)
    except Exception as exc:  # noqa: BLE001
        msg = f"Erreur collecte {scraper.nom} : {exc}"
        logger.exception(msg)
        resultat.erreurs.append(str(exc))
        resultat.duree_ms = int((time.monotonic() - debut) * 1000)
        _journaliser(
            session,
            agent="ARGOS",
            niveau=NiveauLog.ERROR,
            message=msg,
            portail_id=portail.id,
        )
        portail.derniere_collecte = _utcnow()
        session.add(portail)
        session.commit()
        return resultat

    resultat.items = items
    resultat.ao_trouves = len(items)

    for item in items:
        if filtre.actif and not filtre.correspond(item):
            resultat.ao_filtres += 1
            continue
        if _existe(session, portail.id, item):
            resultat.ao_dedoublonnes += 1
            continue
        ao = _en_modele(item, portail.id)
        session.add(ao)
        resultat.ao_nouveaux += 1

    portail.derniere_collecte = _utcnow()
    portail.maj_le = _utcnow()
    session.add(portail)
    session.commit()

    resultat.duree_ms = int((time.monotonic() - debut) * 1000)

    _journaliser(
        session,
        agent="ARGOS",
        niveau=NiveauLog.INFO,
        message=(
            f"Collecte {scraper.nom} : {resultat.ao_nouveaux} nouveaux / "
            f"{resultat.ao_trouves} trouvés "
            f"(dédoublonnés : {resultat.ao_dedoublonnes}, "
            f"filtrés : {resultat.ao_filtres}) "
            f"en {resultat.duree_ms} ms"
        ),
        portail_id=portail.id,
    )
    return resultat


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _portail_ou_creer(session: Session, scraper: Scraper) -> Portail:
    portail = session.exec(select(Portail).where(Portail.nom == scraper.nom)).first()
    if portail is None:
        portail = Portail(nom=scraper.nom, url_base=scraper.url_base, actif=True)
        session.add(portail)
        session.commit()
        session.refresh(portail)
    return portail


def _injecter_credentials(scraper: Scraper, portail: Portail) -> None:
    """Fournit les credentials déchiffrés aux scrapers qui les supportent."""
    if not hasattr(scraper, "credentials") or portail.credentials_chiffres is None:
        return
    try:
        credentials = dechiffrer_credentials(portail.credentials_chiffres)
    except ErreurCredentials:
        logger.exception(f"Credentials ARGOS invalides pour le portail {portail.nom}")
        raise
    scraper.credentials = credentials or {}


def _injecter_filtre(scraper: Scraper, filtre) -> None:
    """Pousse les mots-clés au scraper pour un filtrage côté API si supporté.

    Best-effort : un scraper qui n'expose pas ces attributs (factices de test,
    portails sans API filtrable) les ignore simplement.
    """
    if hasattr(scraper, "filtre_inclus"):
        scraper.filtre_inclus = tuple(filtre.inclus)
    if hasattr(scraper, "filtre_exclus"):
        scraper.filtre_exclus = tuple(filtre.exclus)


def _injecter_fenetre(scraper: Scraper, portail: Portail) -> None:
    """Pousse la date de dernière collecte au scraper pour l'incrémental.

    Best-effort : un scraper sans cet attribut (factices de test, portails non
    paginables) l'ignore. `None` à la première collecte → rattrapage complet.
    """
    if hasattr(scraper, "depuis"):
        scraper.depuis = portail.derniere_collecte


def _existe(session: Session, portail_id: int | None, item: AOCollecte) -> bool:
    """Détecte les doublons par référence externe puis par url_source."""
    if item.reference_externe:
        existant = session.exec(
            select(AppelOffre).where(
                AppelOffre.portail_id == portail_id,
                AppelOffre.reference_externe == item.reference_externe,
            )
        ).first()
        if existant:
            return True

    existant_url = session.exec(
        select(AppelOffre).where(AppelOffre.url_source == item.url_source)
    ).first()
    return existant_url is not None


def _en_modele(item: AOCollecte, portail_id: int | None) -> AppelOffre:
    return AppelOffre(
        portail_id=portail_id,
        reference_externe=item.reference_externe,
        url_source=item.url_source,
        titre=item.titre,
        emetteur=item.emetteur,
        objet=item.objet,
        budget_estime=item.budget_estime,
        devise=item.devise,
        date_publication=item.date_publication,
        date_limite=item.date_limite,
        type_marche=item.type_marche,
        zone_geographique=item.zone_geographique,
        code_naf=item.code_naf,
        statut=StatutAO.BRUT,
    )


def _journaliser(
    session: Session,
    *,
    agent: str,
    niveau: NiveauLog,
    message: str,
    portail_id: int | None = None,
    appel_offre_id: int | None = None,
) -> None:
    log = LogAgent(
        agent=agent,
        niveau=niveau,
        message=message,
        portail_id=portail_id,
        appel_offre_id=appel_offre_id,
    )
    session.add(log)
    session.commit()
