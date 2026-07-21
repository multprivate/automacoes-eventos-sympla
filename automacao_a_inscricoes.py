"""
Automação A: a cada execução, descobre sozinha quais eventos estão
próximos de acontecer na Sympla (list_upcoming_events — não depende mais
de uma lista fixa de IDs) e casa cada inscrito com um Lead do Bitrix24 por
telefone ou, se não achar, por nome (ignorando
maiúsculas/acentos/espaçamento). Quando acha, avança o Lead pra "Inscrito
Pro Evento" e preenche Data do evento + Nome do evento + o ID interno do
evento Sympla. Quando não acha, cria um Lead novo.

É idempotente: só escreve os campos que realmente mudaram, então pode
rodar quantas vezes quiser (pensada pra rodar a cada 15 minutos via
GitHub Actions — veja .github/workflows/automacao_a.yml).

Uso:
    python automacao_a_inscricoes.py
"""

import logging

from common import (
    bitrix_call,
    bitrix_list_all,
    find_lead_ids_by_phone,
    format_phone_br,
    extract_phone,
    get_lead,
    get_sympla_all_participants,
    list_upcoming_events,
    normalize_name,
    participant_full_name,
    resolve_enum_id,
    FIELD_DATA_DO_EVENTO,
    FIELD_NOME_DO_EVENTO,
    FIELD_SYMPLA_EVENT_ID,
    FIELD_ORIGEM,
    ORIGEM_VALOR_FORMULARIO,
    STAGE_INSCRITO_PRO_EVENTO,
    STAGES_SAFE_TO_ADVANCE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("automacao_a_inscricoes")


def load_leads_by_normalized_name() -> dict[str, list[dict]]:
    """Busca todos os Leads uma vez e indexa pelo NAME normalizado, pra
    servir de fallback de matching quando o telefone não bate."""
    leads = bitrix_list_all("crm.lead.list", {"select": ["ID", "NAME", "STATUS_ID"]})
    index: dict[str, list[dict]] = {}
    for lead in leads:
        key = normalize_name(lead.get("NAME", ""))
        if not key:
            continue
        index.setdefault(key, []).append(lead)
    return index


def find_lead_ids_by_name(name_index: dict[str, list[dict]], full_name: str) -> list[int]:
    key = normalize_name(full_name)
    if not key:
        return []
    return [int(lead["ID"]) for lead in name_index.get(key, [])]


def build_fields_to_advance(lead: dict, event_name: str, event_date: str, sympla_event_id: str) -> dict:
    """Monta só os campos que precisam mudar nesse Lead (idempotência)."""
    fields = {}
    status = lead.get("STATUS_ID")
    if status in STAGES_SAFE_TO_ADVANCE:
        fields["STATUS_ID"] = STAGE_INSCRITO_PRO_EVENTO
    elif status != STAGE_INSCRITO_PRO_EVENTO:
        log.info("Lead %s já está em estágio avançado (%s), não mexendo no estágio.", lead.get("ID"), status)

    if FIELD_DATA_DO_EVENTO and lead.get(FIELD_DATA_DO_EVENTO) != event_date:
        fields[FIELD_DATA_DO_EVENTO] = event_date
    if FIELD_NOME_DO_EVENTO and lead.get(FIELD_NOME_DO_EVENTO) != event_name:
        fields[FIELD_NOME_DO_EVENTO] = event_name
    if FIELD_SYMPLA_EVENT_ID and lead.get(FIELD_SYMPLA_EVENT_ID) != sympla_event_id:
        fields[FIELD_SYMPLA_EVENT_ID] = sympla_event_id
    return fields


def create_lead_from_participant(participant: dict, phone_raw: str, event_name: str, event_date: str, sympla_event_id: str) -> None:
    name = participant_full_name(participant)
    fields = {
        "NAME": name or "Inscrito Sympla",
        "TITLE": name or "Inscrito Sympla",
        "PHONE": [{"VALUE": format_phone_br(phone_raw), "VALUE_TYPE": "WORK"}],
        "STATUS_ID": STAGE_INSCRITO_PRO_EVENTO,
    }
    if FIELD_DATA_DO_EVENTO:
        fields[FIELD_DATA_DO_EVENTO] = event_date
    if FIELD_NOME_DO_EVENTO:
        fields[FIELD_NOME_DO_EVENTO] = event_name
    if FIELD_SYMPLA_EVENT_ID:
        fields[FIELD_SYMPLA_EVENT_ID] = sympla_event_id
    if FIELD_ORIGEM:
        fields[FIELD_ORIGEM] = resolve_enum_id(FIELD_ORIGEM, ORIGEM_VALOR_FORMULARIO)
    email = participant.get("email")
    if email:
        fields["EMAIL"] = [{"VALUE": email, "VALUE_TYPE": "WORK"}]

    new_id = bitrix_call("crm.lead.add", {"fields": fields})
    log.info("Novo lead %s criado pro participante %s (%s).", new_id, participant.get("id"), name)


def process_event(event: dict, name_index: dict[str, list[dict]]) -> None:
    event_id = event["id"]
    event_name = event.get("name", "")
    event_date = (event.get("start_date") or "")[:10]  # YYYY-MM-DD

    log.info("Consultando inscritos do evento %s (id interno %s)...", event_name, event_id)
    participants = get_sympla_all_participants(event_id)
    log.info("%d inscrito(s) encontrado(s).", len(participants))

    for participant in participants:
        phone_raw = extract_phone(participant)
        phone_key = format_phone_br(phone_raw)
        full_name = participant_full_name(participant)

        try:
            lead_ids = find_lead_ids_by_phone(phone_key) if phone_key else []
            match_method = "telefone"
            if not lead_ids:
                lead_ids = find_lead_ids_by_name(name_index, full_name)
                match_method = "nome"
        except Exception as exc:
            log.error("Falha ao buscar lead pro inscrito %s: %s", participant.get("id"), exc)
            continue

        try:
            if lead_ids:
                for lead_id in lead_ids:
                    lead = get_lead(lead_id)
                    fields = build_fields_to_advance(lead, event_name, event_date, event_id)
                    if fields:
                        bitrix_call("crm.lead.update", {"id": lead_id, "fields": fields})
                        log.info("Lead %s atualizado (match por %s): %s", lead_id, match_method, fields)
                    else:
                        log.info("Lead %s já estava em dia, nada pra atualizar.", lead_id)
            elif phone_key:
                create_lead_from_participant(participant, phone_raw, event_name, event_date, event_id)
            else:
                log.warning("Inscrito sem telefone e sem nome batendo com Lead existente, pulando: %s", participant.get("id"))
        except Exception as exc:
            log.error("Falha ao processar inscrito %s: %s", participant.get("id"), exc)


def main() -> None:
    name_index = load_leads_by_normalized_name()
    events = list_upcoming_events()
    log.info("%d evento(s) próximo(s) encontrado(s) na Sympla.", len(events))
    for event in events:
        process_event(event, name_index)


if __name__ == "__main__":
    main()
