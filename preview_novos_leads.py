"""
Modo de pré-visualização, só-leitura: mostra exatamente o que a
Automação A FARIA em CADA inscrito de cada evento próximo — criar Lead
(com qual Origem/Responsável) ou atualizar Lead existente (com quais
campos) — sem chamar nenhum endpoint de ESCRITA do Bitrix
(crm.lead.add/crm.lead.update/userfield.update). As únicas chamadas que
saem são leituras (Sympla, crm.duplicate.findbycomm, crm.lead.list,
crm.lead.get, user.get) — nenhuma delas muda dado nenhum.

Ignora de propósito o cache de "já processado" da Automação A (mostra
TODO mundo, não só quem seria "novo") — é só pra validação manual, não
precisa refletir o filtro de produção.

Uso:
    python preview_novos_leads.py
"""

import logging
import os

from automacao_a_inscricoes import (
    build_cupom_map_loader,
    build_fields_to_advance,
    find_matching_lead_ids,
    resolve_assessor_and_origem,
)
from common import (
    extract_discount_code,
    extract_phone,
    format_phone_br,
    get_lead,
    get_sympla_all_participants,
    list_upcoming_events,
    participant_full_name,
    resolve_user_id_by_email,
    OLD_FUNNEL_STAGES,
)

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("preview_novos_leads")


def preview_participant(participant: dict, event_name: str, event_date: str, event_id: str, get_cupom_map) -> None:
    phone_raw = extract_phone(participant)
    phone_key = format_phone_br(phone_raw)
    email = participant.get("email") or ""
    full_name = participant_full_name(participant)
    pid = participant.get("id")

    lead_ids, match_method = find_matching_lead_ids(phone_key, email, full_name)

    if lead_ids:
        for lead_id in lead_ids:
            lead = get_lead(lead_id)
            is_old_funnel = lead.get("STATUS_ID") in OLD_FUNNEL_STAGES
            fields = build_fields_to_advance(lead, event_name, event_date, event_id)
            if is_old_funnel:
                fields.pop("STATUS_ID", None)
            tag = " [FUNIL ANTIGO - só campos de evento, estágio intocado]" if is_old_funnel else ""
            if fields:
                print(f"  [ATUALIZARIA]{tag} {pid} {full_name} -> Lead {lead_id} (match {match_method}): {fields}")
            else:
                print(f"  [SEM MUDANÇA] {pid} {full_name} -> Lead {lead_id} (match {match_method}) já está em dia")
        return

    if not phone_key:
        print(f"  [PULARIA] {pid} {full_name}: sem telefone e sem match por nome/e-mail")
        return

    cupom = extract_discount_code(participant, get_cupom_map)
    assessor_email, origem = resolve_assessor_and_origem(cupom)

    responsavel_info = ""
    if assessor_email:
        try:
            user_id = resolve_user_id_by_email(assessor_email)
            responsavel_info = f", responsável={assessor_email} (Bitrix user {user_id} ✓)"
        except Exception as exc:
            responsavel_info = f", responsável={assessor_email} (⚠ FALHOU resolver no Bitrix: {exc})"

    print(f"  [CRIARIA Lead novo] {pid} {full_name}: cupom={cupom!r}, origem={origem!r}{responsavel_info}")


def preview_event(event: dict) -> None:
    event_id = event["id"]
    event_name = event.get("name", "")
    event_date = (event.get("start_date") or "")[:10]

    participants = get_sympla_all_participants(event_id)
    print(f"\n=== {event_name} ({event_id}) — {len(participants)} inscrito(s) no total ===")
    if not participants:
        return

    get_cupom_map = build_cupom_map_loader(event_id)
    for participant in participants:
        preview_participant(participant, event_name, event_date, event_id, get_cupom_map)


def main() -> None:
    test_event_ids = {e.strip() for e in os.environ.get("TEST_EVENT_IDS", "").split(",") if e.strip()}

    events = list_upcoming_events()
    print(f"{len(events)} evento(s) próximo(s) encontrado(s) na Sympla.")

    if test_event_ids:
        events = [e for e in events if e["id"] in test_event_ids]
        print(f"Modo teste ativo (TEST_EVENT_IDS) — restrito a {len(events)} evento(s): {sorted(test_event_ids)}")

    for event in events:
        preview_event(event)


if __name__ == "__main__":
    main()
