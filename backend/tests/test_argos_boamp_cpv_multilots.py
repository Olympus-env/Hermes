"""CPV principal / acheteur des avis BOAMP eForms multi-lots (issue #69).

Fixture : extrait minimal de l'avis réel 26-98275 (assurances, 3 lots dont les CPV
diffèrent du CPV principal du projet racine).
"""

import copy
import json
from pathlib import Path
from typing import Any

from hermes.agents.argos.boamp import extraire_identifiants

_FIXTURE = Path(__file__).parent / "fixtures" / "avis_eforms_multilots.json"


def _avis() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _notice(avis: dict[str, Any]) -> dict[str, Any]:
    return avis["EFORMS"]["ContractNotice"]


def test_cpv_principal_lu_sur_le_projet_racine():
    assert extraire_identifiants(_avis()) == ("20006846800012", "66510000")


def test_cpv_principal_independant_de_l_ordre_des_cles():
    """Les lots placés avant le projet racine ne doivent pas voler le CPV principal."""
    notice = _notice(_avis())
    reordonne = {
        "cac:ProcurementProjectLot": notice["cac:ProcurementProjectLot"],
        **{k: v for k, v in notice.items() if k != "cac:ProcurementProjectLot"},
    }
    assert list(reordonne)[0] == "cac:ProcurementProjectLot"
    assert extraire_identifiants({"EFORMS": {"ContractNotice": reordonne}})[1] == "66510000"


def test_cpv_repli_sur_le_premier_lot_si_racine_sans_cpv():
    avis = copy.deepcopy(_avis())
    del _notice(avis)["cac:ProcurementProject"]["cac:MainCommodityClassification"]
    assert extraire_identifiants(avis)[1] == "66515200"


def test_cpv_principal_liste_dans_le_projet_racine():
    avis = copy.deepcopy(_avis())
    projet = _notice(avis)["cac:ProcurementProject"]
    projet["cac:MainCommodityClassification"] = [
        projet["cac:MainCommodityClassification"],
        {"cbc:ItemClassificationCode": {"@listName": "cpv", "#text": "11111111"}},
    ]
    assert extraire_identifiants(avis)[1] == "66510000"


def test_siret_premier_acheteur_dans_l_ordre_du_document():
    """Avec deux ContractingParty, le SIRET retenu est celui du premier acheteur."""
    avis = copy.deepcopy(_avis())
    notice = _notice(avis)
    second = copy.deepcopy(notice["cac:ContractingParty"])
    second["cac:Party"]["cac:PartyIdentification"]["cbc:ID"]["#text"] = "ORG-0002"
    notice["cac:ContractingParty"] = [notice["cac:ContractingParty"], second]
    assert extraire_identifiants(avis)[0] == "20006846800012"
    notice["cac:ContractingParty"].reverse()
    assert extraire_identifiants(avis)[0] == "17140005400010"


def test_siret_second_acheteur_si_premier_sans_siret_valide():
    avis = copy.deepcopy(_avis())
    notice = _notice(avis)
    orgs = notice["ext:UBLExtensions"]["ext:UBLExtension"]["ext:ExtensionContent"][
        "efext:EformsExtension"
    ]["efac:Organizations"]["efac:Organization"]
    orgs[0]["efac:Company"]["cac:PartyLegalEntity"]["cbc:CompanyID"] = "n/a"
    second = copy.deepcopy(notice["cac:ContractingParty"])
    second["cac:Party"]["cac:PartyIdentification"]["cbc:ID"]["#text"] = "ORG-0002"
    notice["cac:ContractingParty"] = [notice["cac:ContractingParty"], second]
    assert extraire_identifiants(avis)[0] == "17140005400010"
