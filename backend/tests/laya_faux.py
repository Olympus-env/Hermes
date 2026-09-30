"""Moteur Laya simulé pour les tests : aucun modèle, aucun réseau, résultats déterministes."""

from __future__ import annotations

import math

from hermes.agents.krinos.laya_moteur import QuestionLaya, SortieLaya


class MoteurSimule:
    """Répond selon des probabilités cibles.

    - `score` : logit `marge` sur le niveau `niveau` (0-4), 0 ailleurs — marge élevée =
      distribution quasi certaine (score ≈ niveau/4·100, confiance ≈ 1) ; marge faible =
      distribution étalée (confiance basse).
    - `noul` : P(vrai) = `pertinence` (question « pertinence ») ou `manipulation`.
    """

    def __init__(
        self,
        niveau: int = 3,
        pertinence: float = 0.9,
        manipulation: float = 0.02,
        marge: float = 12.0,
        erreur: Exception | None = None,
    ) -> None:
        self.niveau = niveau
        self.pertinence = pertinence
        self.manipulation = manipulation
        self.marge = marge
        self.erreur = erreur
        self.appels: list[tuple[str, dict[str, QuestionLaya]]] = []

    def evaluer(self, etat: str, questions: dict[str, QuestionLaya]) -> dict[str, SortieLaya]:
        self.appels.append((etat, dict(questions)))
        if self.erreur is not None:
            raise self.erreur
        sorties: dict[str, SortieLaya] = {}
        for nom, q in questions.items():
            if q.type == "score":
                logits = [0.0] * len(q.criteres)
                logits[self.niveau] = self.marge
            else:
                p = self.pertinence if nom == "pertinence" else self.manipulation
                logits = [0.0, math.log(p / (1 - p))]
            sorties[nom] = SortieLaya(logits=logits, act_probabilite=0.5, tokens=100)
        return sorties
