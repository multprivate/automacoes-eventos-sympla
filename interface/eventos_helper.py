"""
Lista de eventos pra EXIBIÇÃO no painel (Dashboard/Eventos) — diferente de
common.list_upcoming_events(), que existe pro motor de sincronização
decidir o que processar (só futuros) e não deve ser usada aqui: um evento
já sincronizado não pode simplesmente sumir da tela só porque a data já
passou.

União de eventos_config (todo evento já sincronizado alguma vez, passado
ou futuro) com list_upcoming_events() (futuros que ainda não têm linha em
eventos_config — evento novo, pra o admin já poder ver/ativar antes do
primeiro sync automático).
"""

import logging

from common import list_upcoming_events
from repositories import eventos_config_repo

log = logging.getLogger("interface.eventos_helper")


def list_all_events_view() -> list[dict]:
    try:
        config_rows = eventos_config_repo.get_all()
    except Exception as exc:
        log.warning("Falha ao ler eventos_config: %s", exc)
        config_rows = []

    try:
        upcoming = list_upcoming_events()
    except Exception as exc:
        log.warning("Falha ao buscar eventos da Sympla: %s", exc)
        upcoming = []
    upcoming_by_id = {e["id"]: e for e in upcoming}

    view = []
    seen = set()
    for row in config_rows:
        event_id = row["sympla_event_id"]
        seen.add(event_id)
        sympla_event = upcoming_by_id.get(event_id)
        view.append(
            {
                "id": event_id,
                "nome": (sympla_event.get("name") if sympla_event else row.get("nome_evento")) or "",
                "data": ((sympla_event.get("start_date") or "")[:10] if sympla_event else row.get("data_evento")) or "",
                "inscritos": row.get("inscritos_count", 0),
                "presentes": row.get("presentes_count", 0),
                "ultimo_sync": row.get("ultimo_sync_em"),
                "ativo": row.get("ativo", True),
                "removido": bool(row.get("removido_em")),
                # sync_one_event() só sabe processar eventos que ainda estão
                # em list_upcoming_events() — um evento já passado não pode
                # usar os botões "Sincronizar agora"/"Forçar campos".
                "sincronizavel": event_id in upcoming_by_id,
            }
        )

    for event in upcoming:
        if event["id"] in seen:
            continue
        view.append(
            {
                "id": event["id"],
                "nome": event.get("name", ""),
                "data": (event.get("start_date") or "")[:10],
                "inscritos": 0,
                "presentes": 0,
                "ultimo_sync": None,
                "ativo": True,
                "removido": False,
                "sincronizavel": True,
            }
        )

    view.sort(key=lambda e: e["data"] or "", reverse=True)
    return view
