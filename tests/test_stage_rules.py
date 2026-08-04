from common import (
    FIELD_DATA_DO_EVENTO,
    FIELD_NOME_DO_EVENTO,
    FIELD_SYMPLA_EVENT_ID,
    STAGE_INSCRITO_PRO_EVENTO,
    STAGES_SAFE_TO_ADVANCE,
)
from domain.stage_rules import build_fields_to_advance

EVENT_NAME = "Workshop Teste"
EVENT_DATE = "2026-03-04"
SYMPLA_EVENT_ID = "s359e77"


def test_avanca_estagio_quando_lead_esta_em_estagio_seguro():
    safe_stage = next(iter(STAGES_SAFE_TO_ADVANCE))
    lead = {"ID": 1, "STATUS_ID": safe_stage}
    fields = build_fields_to_advance(lead, EVENT_NAME, EVENT_DATE, SYMPLA_EVENT_ID, "")
    assert fields.get("STATUS_ID") == STAGE_INSCRITO_PRO_EVENTO


def test_nao_avanca_quando_lead_ja_esta_no_estagio_alvo():
    lead = {"ID": 1, "STATUS_ID": STAGE_INSCRITO_PRO_EVENTO}
    fields = build_fields_to_advance(lead, EVENT_NAME, EVENT_DATE, SYMPLA_EVENT_ID, "")
    assert "STATUS_ID" not in fields


def test_nao_avanca_quando_lead_esta_em_estagio_alem_do_seguro():
    """Lead num estágio avançado qualquer (não seguro, não é o alvo) não
    tem o estágio mexido — só quem está em STAGES_SAFE_TO_ADVANCE avança."""
    lead = {"ID": 1, "STATUS_ID": "CONVERTED"}
    fields = build_fields_to_advance(lead, EVENT_NAME, EVENT_DATE, SYMPLA_EVENT_ID, "")
    assert "STATUS_ID" not in fields


def test_so_inclui_campos_que_realmente_mudaram():
    safe_stage = next(iter(STAGES_SAFE_TO_ADVANCE))
    lead = {
        "ID": 1,
        "STATUS_ID": safe_stage,
        FIELD_DATA_DO_EVENTO: EVENT_DATE,  # já está igual — não deve reaparecer no diff
        FIELD_NOME_DO_EVENTO: "Nome Antigo",  # diferente — deve aparecer
    }
    fields = build_fields_to_advance(lead, EVENT_NAME, EVENT_DATE, SYMPLA_EVENT_ID, "")
    assert FIELD_DATA_DO_EVENTO not in fields
    assert fields.get(FIELD_NOME_DO_EVENTO) == EVENT_NAME
    assert fields.get(FIELD_SYMPLA_EVENT_ID) == SYMPLA_EVENT_ID


def test_lead_totalmente_em_dia_nao_gera_nenhum_campo():
    lead = {
        "ID": 1,
        "STATUS_ID": STAGE_INSCRITO_PRO_EVENTO,
        FIELD_DATA_DO_EVENTO: EVENT_DATE,
        FIELD_NOME_DO_EVENTO: EVENT_NAME,
        FIELD_SYMPLA_EVENT_ID: SYMPLA_EVENT_ID,
    }
    fields = build_fields_to_advance(lead, EVENT_NAME, EVENT_DATE, SYMPLA_EVENT_ID, "")
    assert fields == {}


def test_force_reenvia_campos_mesmo_ja_iguais():
    """force=True ('Forçar atualização de campos' no painel) reenvia os
    campos de evento mesmo que já estejam batendo — mas não força o
    estágio, só os 4 campos de evento."""
    lead = {
        "ID": 1,
        "STATUS_ID": STAGE_INSCRITO_PRO_EVENTO,
        FIELD_DATA_DO_EVENTO: EVENT_DATE,
        FIELD_NOME_DO_EVENTO: EVENT_NAME,
        FIELD_SYMPLA_EVENT_ID: SYMPLA_EVENT_ID,
    }
    fields = build_fields_to_advance(lead, EVENT_NAME, EVENT_DATE, SYMPLA_EVENT_ID, "", force=True)
    assert fields.get(FIELD_DATA_DO_EVENTO) == EVENT_DATE
    assert fields.get(FIELD_NOME_DO_EVENTO) == EVENT_NAME
    assert fields.get(FIELD_SYMPLA_EVENT_ID) == SYMPLA_EVENT_ID
    assert "STATUS_ID" not in fields  # lead já estava no estágio alvo — force não muda isso


def test_force_nao_promove_lead_de_funil_alem_do_seguro():
    lead = {"ID": 1, "STATUS_ID": "CONVERTED", FIELD_DATA_DO_EVENTO: EVENT_DATE}
    fields = build_fields_to_advance(lead, EVENT_NAME, EVENT_DATE, SYMPLA_EVENT_ID, "", force=True)
    assert "STATUS_ID" not in fields


def test_field_config_dinamico_via_keyword_override():
    """Confirma que os codes de campo/estágio podem ser sobrescritos por
    parâmetro (usado por services/lead_sync_service.py, que resolve os
    valores via services/config_service.py em vez do default de
    common/constants.py)."""
    safe_stage = next(iter(STAGES_SAFE_TO_ADVANCE))
    lead = {"ID": 1, "STATUS_ID": safe_stage}
    fields = build_fields_to_advance(
        lead, EVENT_NAME, EVENT_DATE, SYMPLA_EVENT_ID, "",
        field_data_do_evento="UF_CRM_OUTRO_CAMPO",
        stage_alvo="OUTRO_ESTAGIO",
    )
    assert fields.get("STATUS_ID") == "OUTRO_ESTAGIO"
    assert fields.get("UF_CRM_OUTRO_CAMPO") == EVENT_DATE
    assert FIELD_DATA_DO_EVENTO not in fields
