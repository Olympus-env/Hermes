"""Modèles MNEMOSYNE — schéma de la base SQLite.

Les huit tables correspondent au cahier des charges HERMES v1.0 § 6.

Note : ne PAS utiliser `from __future__ import annotations` ici — SQLModel/SQLAlchemy
introspectent les annotations à l'exécution pour configurer les relations,
ce qui exige des types réels (pas des chaînes).
"""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from sqlmodel import Column, Field, LargeBinary, Relationship, SQLModel, Text


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Énumérations
# --------------------------------------------------------------------------- #


class StatutAO(str, Enum):
    BRUT = "brut"
    ANALYSE = "analyse"
    A_REPONDRE = "a_repondre"
    EN_REDACTION = "en_redaction"
    REPONDU = "repondu"
    REJETE = "rejete"
    EXPIRE = "expire"


class StatutReponse(str, Enum):
    EN_GENERATION = "en_generation"
    EN_ATTENTE = "en_attente"
    A_MODIFIER = "a_modifier"
    VALIDEE = "validee"
    REJETEE = "rejetee"
    EXPORTEE = "exportee"


class TypePortail(str, Enum):
    PUBLIC = "public"
    PRIVE = "prive"


class TypeDocument(str, Enum):
    PDF = "pdf"
    XLSX = "xlsx"
    DOCX = "docx"
    HTML = "html"
    AUTRE = "autre"


class NiveauLog(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #


class Portail(SQLModel, table=True):
    """Sources de scraping configurées (BOAMP, TED, etc.)."""

    __tablename__ = "portails"

    id: Optional[int] = Field(default=None, primary_key=True)
    nom: str = Field(index=True, unique=True)
    url_base: str
    type: TypePortail = TypePortail.PUBLIC
    actif: bool = Field(default=True, index=True)

    # Sélecteurs / config scraping (JSON-encodé en str pour SQLite simple)
    config_scraping: Optional[str] = Field(default=None, sa_column=Column(Text))
    # Credentials chiffrés AES-256 (NULL si portail public)
    credentials_chiffres: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary)
    )

    frequence_minutes: int = Field(default=360)  # 6h par défaut
    derniere_collecte: Optional[datetime] = None

    cree_le: datetime = Field(default_factory=_utcnow)
    maj_le: datetime = Field(default_factory=_utcnow)

    appels_offre: List["AppelOffre"] = Relationship(back_populates="portail")


class AppelOffre(SQLModel, table=True):
    """Table centrale — un appel d'offre détecté par ARGOS."""

    __tablename__ = "appels_offre"

    id: Optional[int] = Field(default=None, primary_key=True)
    portail_id: Optional[int] = Field(default=None, foreign_key="portails.id", index=True)

    # Identifiant externe (n° d'avis BOAMP, ref TED…)
    reference_externe: Optional[str] = Field(default=None, index=True)
    url_source: str

    titre: str = Field(index=True)
    emetteur: Optional[str] = Field(default=None, index=True)
    objet: Optional[str] = Field(default=None, sa_column=Column(Text))

    budget_estime: Optional[float] = None
    devise: str = Field(default="EUR")

    date_publication: Optional[datetime] = None
    date_limite: Optional[datetime] = Field(default=None, index=True)

    type_marche: Optional[str] = None
    zone_geographique: Optional[str] = None
    code_naf: Optional[str] = Field(default=None, index=True)

    statut: StatutAO = Field(default=StatutAO.BRUT, index=True)

    cree_le: datetime = Field(default_factory=_utcnow, index=True)
    maj_le: datetime = Field(default_factory=_utcnow)

    portail: Optional[Portail] = Relationship(back_populates="appels_offre")
    documents: List["Document"] = Relationship(back_populates="appel_offre")
    analyses: List["AnalyseKrinos"] = Relationship(back_populates="appel_offre")
    reponses: List["ReponseHermion"] = Relationship(back_populates="appel_offre")


class Document(SQLModel, table=True):
    """Fichiers téléchargés associés à un AO (PDF, xlsx, html, etc.)."""

    __tablename__ = "documents"

    id: Optional[int] = Field(default=None, primary_key=True)
    appel_offre_id: int = Field(foreign_key="appels_offre.id", index=True)

    nom_fichier: str
    chemin_local: str  # chemin relatif sous storage/
    type: TypeDocument = TypeDocument.AUTRE
    taille_octets: int = 0
    checksum_sha256: str = Field(index=True)

    contenu_extrait: Optional[str] = Field(default=None, sa_column=Column(Text))

    cree_le: datetime = Field(default_factory=_utcnow)

    appel_offre: Optional[AppelOffre] = Relationship(back_populates="documents")


class AnalyseKrinos(SQLModel, table=True):
    """Analyse produite par KRINOS pour un AO donné."""

    __tablename__ = "analyses_krinos"

    id: Optional[int] = Field(default=None, primary_key=True)
    appel_offre_id: int = Field(foreign_key="appels_offre.id", index=True)

    resume: str = Field(sa_column=Column(Text))
    score: float = Field(index=True)  # 0-100 (score pondéré final)
    justification_score: str = Field(sa_column=Column(Text))

    # Tags JSON-string : ["bâtiment", "rénovation", ...]
    tags: Optional[str] = Field(default=None, sa_column=Column(Text))
    criteres_extraits: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Scores 0-100 par dimension (JSON) — utilisés avec la pondération
    # utilisateur pour calculer `score`. Permet de recalculer le score
    # si l'utilisateur change la pondération sans relancer PYTHIA.
    scores_dimensions: Optional[str] = Field(default=None, sa_column=Column(Text))

    duree_analyse_ms: Optional[int] = None
    modele_llm: Optional[str] = None  # ex: mistral:7b-instruct-q4_K_M

    cree_le: datetime = Field(default_factory=_utcnow, index=True)

    appel_offre: Optional[AppelOffre] = Relationship(back_populates="analyses")


class ReponseHermion(SQLModel, table=True):
    """Versions de réponse rédigées par HERMION pour un AO."""

    __tablename__ = "reponses_hermion"

    id: Optional[int] = Field(default=None, primary_key=True)
    appel_offre_id: int = Field(foreign_key="appels_offre.id", index=True)

    version: int = Field(default=1)
    contenu: str = Field(sa_column=Column(Text))

    statut: StatutReponse = Field(default=StatutReponse.EN_GENERATION, index=True)
    workflow_utilise: Optional[str] = Field(default=None, sa_column=Column(Text))

    # IDs des entrées base_connaissances utilisées (JSON list)
    sources_kb: Optional[str] = Field(default=None, sa_column=Column(Text))

    longueur_mots: Optional[int] = None
    duree_generation_ms: Optional[int] = None

    commentaire_humain: Optional[str] = Field(default=None, sa_column=Column(Text))
    chemin_export: Optional[str] = None  # rempli après export PDF

    cree_le: datetime = Field(default_factory=_utcnow, index=True)
    maj_le: datetime = Field(default_factory=_utcnow)

    appel_offre: Optional[AppelOffre] = Relationship(back_populates="reponses")


class BaseConnaissance(SQLModel, table=True):
    """Index vectoriel — réponses validées et docs de référence."""

    __tablename__ = "base_connaissances"

    id: Optional[int] = Field(default=None, primary_key=True)
    titre: str
    contenu: str = Field(sa_column=Column(Text))
    source: Optional[str] = None  # "reponse_validee" | "doc_reference" | ...
    appel_offre_id: Optional[int] = Field(
        default=None, foreign_key="appels_offre.id", index=True
    )

    embedding: Optional[bytes] = Field(default=None, sa_column=Column(LargeBinary))
    modele_embedding: Optional[str] = None

    actif: bool = Field(default=True, index=True)
    cree_le: datetime = Field(default_factory=_utcnow)


class Parametre(SQLModel, table=True):
    """Paramètres applicatifs clé/valeur."""

    __tablename__ = "parametres"

    cle: str = Field(primary_key=True)
    valeur: str = Field(sa_column=Column(Text))
    description: Optional[str] = None
    maj_le: datetime = Field(default_factory=_utcnow)


class LogAgent(SQLModel, table=True):
    """Journal d'actions des agents (ARGOS, KRINOS, HERMION)."""

    __tablename__ = "logs_agents"

    id: Optional[int] = Field(default=None, primary_key=True)
    agent: str = Field(index=True)  # "ARGOS" | "KRINOS" | "HERMION"
    niveau: NiveauLog = Field(default=NiveauLog.INFO, index=True)
    message: str = Field(sa_column=Column(Text))
    contexte: Optional[str] = Field(default=None, sa_column=Column(Text))

    appel_offre_id: Optional[int] = Field(
        default=None, foreign_key="appels_offre.id", index=True
    )
    portail_id: Optional[int] = Field(default=None, foreign_key="portails.id", index=True)

    cree_le: datetime = Field(default_factory=_utcnow, index=True)
