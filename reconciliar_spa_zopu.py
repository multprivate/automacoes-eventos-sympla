"""
Script pontual: liga os itens antigos da SPA "Eventos Sympla" (criados
pelo app Zopu, já descontinuado) ao ID real do evento na Sympla, casando
por nome+data extraídos do título do item ("Nome do Evento (DD/MM/YYYY)").
Evita que o motor crie um item duplicado pra um evento que a Zopu já tinha
cadastrado — só importa pros itens cujo evento ainda está em
list_upcoming_events() (os passados nunca são retocados pelo motor de
qualquer forma).

Só toca item sem o campo (novo) ainda preenchido, e só em match exato e
único — ambíguo fica de fora, logado pra revisão manual, não adivinha.

Uso:
    python reconciliar_spa_zopu.py           # aplica de verdade
    DRY_RUN=1 python reconciliar_spa_zopu.py # só mostra o que faria
"""

import logging
import os
import re

from common import (
    bitrix_call,
    get_all_events,
    normalize_name,
    spa_update_item,
    FIELD_SPA_SYMPLA_EVENT_ID,
    BITRIX_SPA_ENTITY_TYPE_ID,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("reconciliar_spa_zopu")

TITLE_RE = re.compile(r"^(.*)\((\d{2})/(\d{2})/(\d{4})\)\s*$")


def _event_key(nome: str, dd: str, mm: str, yyyy: str) -> str:
    return f"{normalize_name(nome)}|{dd}/{mm}/{yyyy}"


def main() -> None:
    dry_run = bool(os.environ.get("DRY_RUN"))

    items = bitrix_call("crm.item.list", {"entityTypeId": BITRIX_SPA_ENTITY_TYPE_ID, "select": ["id", "title", FIELD_SPA_SYMPLA_EVENT_ID]})["items"]
    pendentes = [i for i in items if not i.get(FIELD_SPA_SYMPLA_EVENT_ID)]
    if not pendentes:
        log.info("Nenhum item sem %s — nada a reconciliar.", FIELD_SPA_SYMPLA_EVENT_ID)
        return

    events_by_key: dict[str, list[dict]] = {}
    for event in get_all_events():
        date_iso = (event.get("start_date") or "")[:10]
        if len(date_iso) != 10:
            continue
        yyyy, mm, dd = date_iso.split("-")
        key = _event_key(event.get("name", ""), dd, mm, yyyy)
        events_by_key.setdefault(key, []).append(event)

    vinculados = ignorados = 0
    for item in pendentes:
        match = TITLE_RE.match(item.get("title", ""))
        if not match:
            log.warning("Item %s: título '%s' não segue o padrão 'Nome (DD/MM/YYYY)', pulando.", item["id"], item.get("title"))
            ignorados += 1
            continue
        nome, dd, mm, yyyy = match.groups()
        candidatos = events_by_key.get(_event_key(nome, dd, mm, yyyy), [])
        if len(candidatos) != 1:
            log.warning("Item %s ('%s'): %d candidato(s) na Sympla pra essa chave, pulando (precisa de match único).", item["id"], item["title"], len(candidatos))
            ignorados += 1
            continue

        event = candidatos[0]
        log.info("Item %s ('%s') -> evento Sympla %s.", item["id"], item["title"], event["id"])
        if not dry_run:
            spa_update_item(int(item["id"]), {FIELD_SPA_SYMPLA_EVENT_ID: event["id"]})
        vinculados += 1

    log.info("Reconciliação concluída: %d vinculado(s), %d ignorado(s) (de %d pendente(s)).", vinculados, ignorados, len(pendentes))


if __name__ == "__main__":
    main()
