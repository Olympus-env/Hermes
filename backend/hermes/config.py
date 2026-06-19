"""Configuration centrale chargée depuis les variables d'environnement / .env."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _est_url_loopback(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {
        "127.0.0.1",
        "localhost",
        "::1",
    }


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="HERMES_",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False
    # En mode debug le scheduler ne démarre pas automatiquement
    # (évite des collectes répétées pendant le hot-reload).
    scheduler_auto_start: bool = False

    db_path: Path = Field(default=Path("./data/hermes.db"))
    storage_path: Path = Field(default=Path("./data/storage"))
    log_path: Path = Field(default=Path("./data/logs"))
    log_level: str = "INFO"

    master_key: str | None = None
    master_key_path: Path = Field(default=Path("./data/master.key"))

    # PYTHIA — LLM local via Ollama
    ollama_base_url: str = "http://127.0.0.1:11434"
    # Qwen3 8B (q4) : tient entièrement dans 8 Go de VRAM (~72 t/s), bien meilleur
    # que Mistral 7B en français, respect de structure et résumés (fini le
    # « résumé = titre »), sans sortir du local. Override possible via
    # HERMES_PYTHIA_MODELE.
    pythia_modele: str = "qwen3:8b"
    pythia_modele_embeddings: str = "nomic-embed-text"
    pythia_timeout_secondes: float = 180.0
    pythia_temperature: float = 0.2
    # Inférences LLM simultanées autorisées. Ollama traite les requêtes une à
    # une : au-delà de 1, KRINOS et HERMION s'empilent et saturent la machine
    # (issue #4). On sérialise donc par défaut.
    pythia_concurrence_max: int = 1
    # HERMION peut générer des réponses nettement plus longues que KRINOS.
    # Les timeouts sont donc séparés pour éviter de pénaliser les appels courts.
    hermion_plan_timeout_secondes: float = 180.0
    hermion_section_timeout_secondes: float = 420.0
    hermion_section_timeout_par_100_mots_secondes: float = 45.0
    # Nb max de caractères de contenu documentaire injectés dans le prompt KRINOS
    krinos_contexte_max_caracteres: int = 12000

    def model_post_init(self, __context: object) -> None:
        self.host = "127.0.0.1"
        if not _est_url_loopback(self.ollama_base_url):
            self.ollama_base_url = "http://127.0.0.1:11434"

    @property
    def database_url(self) -> str:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.db_path.as_posix()}"

    def ensure_dirs(self) -> None:
        for p in (
            self.db_path.parent,
            self.storage_path,
            self.log_path,
            self.master_key_path.parent,
        ):
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
