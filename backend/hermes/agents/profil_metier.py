"""Profil métier structuré — contexte d'entreprise pour KRINOS (PYTHIA + Laya).

Stocké dans MNEMOSYNE (`parametres`, clé `profil.metier`) au format JSON. Il ne
contient AUCUNE donnée d'identité (nom, prénom, email, SIRET…) : seul le
savoir-faire de la structure, pour rester exploitable par tout juge sans fuite. Le
modèle refuse les champs inconnus et les valeurs qui ressemblent à un email ou
à un SIRET/SIREN.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlmodel import Session

from hermes.db.models import Parametre

CLE_PARAMETRE = "profil.metier"
LONGUEUR_MAX_TEXTE = 1200
MAX_ELEMENTS = 20
MAX_LONGUEUR_ELEMENT = 200

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# SIREN (9 chiffres) / SIRET (14 chiffres), éventuellement séparés par des espaces.
_SIRET = re.compile(r"(?<!\d)(?:\d[ .]?){8}\d(?:[ .]?\d){0,5}(?!\d)")
_CPV = re.compile(r"^\d{8}(-\d)?$")


def _verifier_non_sensible(valeur: str) -> str:
    v = valeur.strip()
    if _EMAIL.search(v):
        raise ValueError("adresse email interdite dans le profil métier")
    for m in _SIRET.finditer(v):
        chiffres = re.sub(r"\D", "", m.group())
        if len(chiffres) in (9, 14):
            raise ValueError("numéro SIREN/SIRET interdit dans le profil métier")
    return v


def _liste_propre(valeurs: list[str]) -> list[str]:
    vus: list[str] = []
    for v in valeurs:
        v = _verifier_non_sensible(v)
        if v and v not in vus:
            vus.append(v)
    if len(vus) > MAX_ELEMENTS:
        raise ValueError(f"maximum {MAX_ELEMENTS} éléments")
    return vus


class ProfilMetier(BaseModel):
    """Profil métier structuré, sans donnée d'identité."""

    model_config = ConfigDict(extra="forbid")

    activite: str = Field(default="", max_length=400)
    secteurs: list[str] = Field(default_factory=list)
    codes_cpv: list[str] = Field(default_factory=list)
    zone_geographique: str = Field(default="", max_length=200)
    effectif: int | None = Field(default=None, ge=0, le=1_000_000)
    ca_tranche: str = Field(default="", max_length=60)
    certifications: list[str] = Field(default_factory=list)
    types_marches: list[str] = Field(default_factory=list)
    references_types: list[str] = Field(default_factory=list)

    @field_validator("activite", "zone_geographique", "ca_tranche")
    @classmethod
    def _texte(cls, v: str) -> str:
        return _verifier_non_sensible(v)

    @field_validator(
        "secteurs", "codes_cpv", "certifications", "types_marches", "references_types"
    )
    @classmethod
    def _liste(cls, v: list[str]) -> list[str]:
        if any(len(x) > MAX_LONGUEUR_ELEMENT for x in v):
            raise ValueError(f"élément trop long (max {MAX_LONGUEUR_ELEMENT} caractères)")
        return _liste_propre(v)

    @field_validator("codes_cpv")
    @classmethod
    def _cpv(cls, v: list[str]) -> list[str]:
        for code in v:
            if not _CPV.match(code):
                raise ValueError(f"code CPV invalide : {code!r}")
        return v

    def est_vide(self) -> bool:
        return not any(self.model_dump().values())


def charger_profil(session: Session) -> ProfilMetier:
    """Profil enregistré ; vide si absent ou illisible."""
    entree = session.get(Parametre, CLE_PARAMETRE)
    if entree is None:
        return ProfilMetier()
    try:
        return ProfilMetier.model_validate_json(entree.valeur)
    except ValueError:
        return ProfilMetier()


def enregistrer_profil(session: Session, profil: ProfilMetier) -> ProfilMetier:
    entree = session.get(Parametre, CLE_PARAMETRE) or Parametre(
        cle=CLE_PARAMETRE,
        valeur="",
        description="Profil métier structuré (KRINOS, Laya, PYTHIA)",
    )
    entree.valeur = profil.model_dump_json()
    entree.maj_le = datetime.now(UTC)
    session.add(entree)
    session.commit()
    return profil


def composer_texte(profil: ProfilMetier, mots_cles: list[str] | tuple[str, ...] = ()) -> str:
    """Texte borné (≤ `LONGUEUR_MAX_TEXTE`) décrivant le profil, complété par les
    mots-clés ARGOS. Les sections les plus importantes viennent en premier."""
    lignes: list[str] = []
    if profil.activite:
        lignes.append(f"Activité : {profil.activite}")
    if profil.secteurs:
        lignes.append("Secteurs : " + ", ".join(profil.secteurs))
    if profil.codes_cpv:
        lignes.append("Codes CPV : " + ", ".join(profil.codes_cpv))
    if profil.types_marches:
        lignes.append("Types de marchés visés : " + ", ".join(profil.types_marches))
    if profil.zone_geographique:
        lignes.append(f"Zone géographique : {profil.zone_geographique}")
    taille = []
    if profil.effectif is not None:
        taille.append(f"{profil.effectif} personnes")
    if profil.ca_tranche:
        taille.append(f"CA {profil.ca_tranche}")
    if taille:
        lignes.append("Taille : " + ", ".join(taille))
    if profil.certifications:
        lignes.append("Certifications : " + ", ".join(profil.certifications))
    if profil.references_types:
        lignes.append("Références types : " + " ; ".join(profil.references_types))
    if mots_cles:
        lignes.append("Mots-clés de veille : " + ", ".join(mots_cles))
    texte = "\n".join(lignes)
    if len(texte) > LONGUEUR_MAX_TEXTE:
        texte = texte[: LONGUEUR_MAX_TEXTE - 1].rstrip() + "…"
    return texte
