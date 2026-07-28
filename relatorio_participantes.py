"""
Relatório pontual, só-leitura: lista todos os participantes de todos os
eventos da Sympla (histórico completo, sem filtro de data) e cruza com o
Bitrix pra saber quem já está cadastrado como Lead.

Não é parte do ciclo das automações — não escreve nada nem no Bitrix nem
na Sympla, só gera um CSV local.

Faz o cruzamento com o Bitrix em massa (busca todos os Leads uma vez só e
compara em memória) em vez de uma chamada de API por participante — o
portal tem milhares de Leads, então checar um por um seria proibitivamente
lento pra um relatório desse tamanho.

Uso:
    python relatorio_participantes.py
"""

import csv
import logging

from common import (
    bitrix_list_all,
    build_cupom_by_order_id,
    extract_discount_code,
    extract_phone,
    format_phone_br,
    get_all_events,
    get_sympla_all_orders,
    get_sympla_all_participants,
    normalize_email,
    normalize_name,
    participant_full_name,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("relatorio_participantes")

OUTPUT_PATH = "relatorio_participantes.csv"
HEADERS = [
    "Nome completo",
    "Email",
    "Telefone",
    "Evento",
    "Data do evento",
    "Cupom",
    "Presente",
    "Cadastrado no Bitrix",
    "Lead ID (Bitrix)",
]


def load_bitrix_lookup() -> tuple[dict[str, list], dict[str, list], dict[str, list]]:
    """Busca todos os Leads do Bitrix uma vez só e indexa por telefone,
    e-mail e nome normalizados, pra cruzar em memória sem precisar de uma
    chamada de API por participante."""
    leads = bitrix_list_all("crm.lead.list", {"select": ["ID", "NAME", "PHONE", "EMAIL"]})
    by_phone: dict[str, list] = {}
    by_email: dict[str, list] = {}
    by_name: dict[str, list] = {}

    for lead in leads:
        lead_id = lead["ID"]
        for phone in lead.get("PHONE") or []:
            key = format_phone_br(phone.get("VALUE", ""))
            if key:
                by_phone.setdefault(key, []).append(lead_id)
        for email in lead.get("EMAIL") or []:
            key = normalize_email(email.get("VALUE", ""))
            if key:
                by_email.setdefault(key, []).append(lead_id)
        key = normalize_name(lead.get("NAME", ""))
        if key:
            by_name.setdefault(key, []).append(lead_id)

    log.info("Lookup do Bitrix pronto: %d lead(s) indexado(s).", len(leads))
    return by_phone, by_email, by_name


def find_lead_id_locally(phone_key: str, email: str, full_name: str, by_phone, by_email, by_name) -> str | None:
    if phone_key and phone_key in by_phone:
        return by_phone[phone_key][0]

    email_key = normalize_email(email)
    if email_key and email_key in by_email:
        return by_email[email_key][0]

    name_key = normalize_name(full_name)
    if name_key and name_key in by_name:
        return by_name[name_key][0]

    return None


def build_rows_for_event(event: dict, by_phone, by_email, by_name) -> list[list[str]]:
    event_id = event["id"]
    event_name = event.get("name", "")
    event_date = (event.get("start_date") or "")[:10]

    participants = get_sympla_all_participants(event_id)
    orders = get_sympla_all_orders(event_id)
    cupom_map = build_cupom_by_order_id(orders)

    def get_cupom_map():
        return cupom_map

    rows = []
    for p in participants:
        full_name = participant_full_name(p)
        email = p.get("email") or ""
        phone_raw = extract_phone(p)
        phone_key = format_phone_br(phone_raw)
        cupom = extract_discount_code(p, get_cupom_map) or "Sem cupom"
        presente = "Sim" if (p.get("checkin") or {}).get("check_in_date") else "Não"

        lead_id = find_lead_id_locally(phone_key, email, full_name, by_phone, by_email, by_name)

        rows.append([
            full_name,
            email,
            phone_raw,
            event_name,
            event_date,
            cupom,
            presente,
            "Sim" if lead_id else "Não",
            lead_id or "",
        ])

    log.info("%s (%s): %d participante(s).", event_name, event_id, len(participants))
    return rows


def main() -> None:
    by_phone, by_email, by_name = load_bitrix_lookup()

    events = get_all_events()
    log.info("%d evento(s) encontrado(s) na Sympla (histórico completo).", len(events))

    all_rows = []
    for event in events:
        all_rows.extend(build_rows_for_event(event, by_phone, by_email, by_name))

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS)
        writer.writerows(all_rows)

    log.info("Pronto: %d linha(s) escrita(s) em %s.", len(all_rows), OUTPUT_PATH)


if __name__ == "__main__":
    main()
