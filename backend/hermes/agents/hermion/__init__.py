"""Agent HERMION — rédaction des réponses aux appels d'offre.

HERMION assemble une réponse en plusieurs étapes via PYTHIA (Qwen3 8B local) :
plan structuré (ou workflow utilisateur) puis rédaction section par section. La
sortie est toujours soumise à validation humaine (StatutReponse.EN_ATTENTE) —
HERMION ne valide ni ne soumet jamais une réponse.
"""

from hermes.agents.hermion.export_pdf import ErreurExportPdf, exporter_reponse_pdf
from hermes.agents.hermion.workflow import (
    SectionWorkflow,
    WorkflowReponse,
    charger_workflow,
    deriver_workflow,
    enregistrer_workflow,
)
from hermes.agents.hermion.writer import (
    ErreurRedactionHermion,
    ProfilUtilisateur,
    ResultatRedaction,
    rediger_reponse,
)

__all__ = [
    "ErreurExportPdf",
    "ErreurRedactionHermion",
    "ProfilUtilisateur",
    "ResultatRedaction",
    "SectionWorkflow",
    "WorkflowReponse",
    "charger_workflow",
    "deriver_workflow",
    "enregistrer_workflow",
    "exporter_reponse_pdf",
    "rediger_reponse",
]
