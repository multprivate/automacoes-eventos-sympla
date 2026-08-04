"""
Roda uma vez (ou sempre que precisar reprocessar): pra todo Lead que já tem
UF_CRM_SYMPLA_EVENT_ID preenchido mas ainda não tem Filtrar Evento certo,
resolve o nome/data do evento correspondente via common.get_all_events()
(cruzando pelo ID interno da Sympla já gravado no Lead — não precisa
rebuscar participantes) e grava o item certo na lista do campo Filtrar
Evento.

Pré-requisito: rodar setup_custom_fields.py antes (cria o campo Filtrar
Evento) e setar BITRIX_FIELD_FILTRAR_EVENTO no .env.

Uso:
    DRY_RUN=1 python backfill_filtrar_evento.py   # só mostra o que faria
    python backfill_filtrar_evento.py             # escreve de verdade
"""
import logging
import os

from common import (
    bitrix_call,
    bitrix_list_all,
    ensure_enum_value,
    format_event_label,
    get_all_events,
    FIELD_FILTRAR_EVENTO,
    FIELD_SYMPLA_EVENT_ID,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("backfill_filtrar_evento")


def main() -> None:
    dry_run = bool(os.environ.get("DRY_RUN"))
    if not FIELD_FILTRAR_EVENTO or not FIELD_SYMPLA_EVENT_ID:
        raise SystemExit("BITRIX_FIELD_FILTRAR_EVENTO e BITRIX_FIELD_SYMPLA_EVENT_ID precisam estar setados no .env.")

    events_by_id = {e["id"]: e for e in get_all_events()}

    leads = bitrix_list_all(
        "crm.lead.list",
        {
            "filter": {"!" + FIELD_SYMPLA_EVENT_ID: ""},
            "select": ["ID", FIELD_SYMPLA_EVENT_ID, FIELD_FILTRAR_EVENTO],
        },
    )
    log.info("%d lead(s) com %s preenchido.", len(leads), FIELD_SYMPLA_EVENT_ID)

    atualizados = ja_ok = sem_evento = erros = 0
    for lead in leads:
        lead_id = lead["ID"]
        event_id = lead.get(FIELD_SYMPLA_EVENT_ID)
        event = events_by_id.get(event_id)
        if not event:
            log.warning("Lead %s: event_id '%s' não encontrado em get_all_events() (evento apagado?), pulando.", lead_id, event_id)
            sem_evento += 1
            continue

        label = format_event_label(event.get("name", ""), (event.get("start_date") or "")[:10])
        try:
            filtrar_evento_id = ensure_enum_value(FIELD_FILTRAR_EVENTO, label)
        except Exception as exc:
            log.error("Lead %s: falha ao resolver '%s': %s", lead_id, label, exc)
            erros += 1
            continue

        if lead.get(FIELD_FILTRAR_EVENTO) == filtrar_evento_id:
            ja_ok += 1
            continue

        if dry_run:
            log.info("[DRY RUN] Lead %s ganharia %s = %s ('%s')", lead_id, FIELD_FILTRAR_EVENTO, filtrar_evento_id, label)
        else:
            bitrix_call("crm.lead.update", {"id": lead_id, "fields": {FIELD_FILTRAR_EVENTO: filtrar_evento_id}})
            log.info("Lead %s atualizado: %s = %s ('%s')", lead_id, FIELD_FILTRAR_EVENTO, filtrar_evento_id, label)
        atualizados += 1

    log.info(
        "Resumo: %d atualizado(s), %d já ok, %d sem evento correspondente, %d erro(s).",
        atualizados, ja_ok, sem_evento, erros,
    )


if __name__ == "__main__":
    main()
