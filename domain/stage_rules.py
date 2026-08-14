"""
Regra de avanço de estágio de um Lead quando bate uma inscrição nova.
Função pura: recebe o Lead já buscado (dict) e os fatos do evento, decide
só quais campos deveriam mudar — quem chama de fato o Bitrix é
automacao_a_inscricoes.py.
"""

import logging

from common import (
    FIELD_DATA_DO_EVENTO,
    FIELD_FILTRAR_EVENTO,
    FIELD_NOME_DO_EVENTO,
    FIELD_SYMPLA_EVENT_ID,
    LEAD_CLOSED_STAGES,
    STAGE_INSCRITO_PRO_EVENTO,
    STAGES_SAFE_TO_ADVANCE,
)

log = logging.getLogger("domain.stage_rules")


def build_fields_to_advance(
    lead: dict,
    event_name: str,
    event_date: str,
    sympla_event_id: str,
    filtrar_evento_id: str,
    force: bool = False,
    *,
    field_data_do_evento: str = FIELD_DATA_DO_EVENTO,
    field_nome_do_evento: str = FIELD_NOME_DO_EVENTO,
    field_sympla_event_id: str = FIELD_SYMPLA_EVENT_ID,
    field_filtrar_evento: str = FIELD_FILTRAR_EVENTO,
    stage_alvo: str = STAGE_INSCRITO_PRO_EVENTO,
) -> dict:
    """Monta só os campos que precisam mudar nesse Lead (idempotência).

    force=True ("Forçar atualização de campos" no painel) reenvia os 4
    campos de evento mesmo que já estejam iguais — não afeta a decisão de
    STATUS_ID, que continua só avançando a partir de STAGES_SAFE_TO_ADVANCE:
    o botão é "forçar campos", não "forçar estágio", e a defesa de nunca
    promover um Lead de funil antigo sozinho precisa continuar valendo
    mesmo com force=True.

    Os `field_*`/`stage_alvo` são keyword-only com default igual ao valor
    fixo de common/constants.py (.env) — quem chama sem passar nada continua
    com o comportamento de sempre; services/lead_sync_service.py passa os
    valores resolvidos dinamicamente via services/config_service.py (tabela
    config_kv, aba Mapeamento do painel)."""
    fields = {}
    status = lead.get("STATUS_ID")
    if status in STAGES_SAFE_TO_ADVANCE:
        fields["STATUS_ID"] = stage_alvo
    elif status != stage_alvo:
        log.info("Lead %s já está em estágio avançado (%s), não mexendo no estágio.", lead.get("ID"), status)

    if field_data_do_evento and (force or lead.get(field_data_do_evento) != event_date):
        fields[field_data_do_evento] = event_date
    if field_nome_do_evento and (force or lead.get(field_nome_do_evento) != event_name):
        fields[field_nome_do_evento] = event_name
    if field_sympla_event_id and (force or lead.get(field_sympla_event_id) != sympla_event_id):
        fields[field_sympla_event_id] = sympla_event_id
    if field_filtrar_evento and filtrar_evento_id and (force or lead.get(field_filtrar_evento) != filtrar_evento_id):
        fields[field_filtrar_evento] = filtrar_evento_id
    return fields


def deve_mover_pos_evento(status_atual: str | None, event_already_happened: bool, force: bool) -> bool:
    """Decide se um Lead deve ser movido pra "Pós Evento" (com "Presente no
    evento" preenchido junto — ver services/lead_sync_service.py) — só
    quando "Forçar atualização de campos" é usado (force=True) num evento
    que já aconteceu.

    Diferente de build_fields_to_advance (que nunca promove um Lead de
    funil antigo sozinho), esta transição vale pra QUALQUER Lead aberto,
    funil novo ou antigo — decisão deliberada: o robô nativo do Bitrix que
    fazia essa transição foi desligado, então sem isso os Leads do funil
    antigo ficariam presos pra sempre sem "Presente no evento" preenchido.

    Só não mexe em Lead já fechado (Ganho/Perdido, LEAD_CLOSED_STAGES) —
    aí a decisão já foi tomada por um humano e não é hora de reabrir."""
    if not (force and event_already_happened):
        return False
    return status_atual not in LEAD_CLOSED_STAGES
