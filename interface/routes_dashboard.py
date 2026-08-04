"""
Dashboard: visão geral (eventos futuros/sincronizados, inscritos
capturados, última sincronização).
"""

import logging

from flask import Blueprint, render_template

from common import list_upcoming_events
from repositories.eventos_config_repo import get_all as get_all_eventos_config
from repositories.logs_repo import list_recent_execucoes

from .auth import login_required

log = logging.getLogger("interface.dashboard")

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    try:
        events = list_upcoming_events()
    except Exception as exc:
        log.warning("Falha ao buscar eventos da Sympla pro Dashboard: %s", exc)
        events = []

    try:
        eventos_config = get_all_eventos_config()
    except Exception as exc:
        log.warning("Falha ao ler eventos_config pro Dashboard: %s", exc)
        eventos_config = []

    config_by_id = {row["sympla_event_id"]: row for row in eventos_config}
    total_sincronizados = sum(1 for row in eventos_config if row.get("ultimo_sync_em"))

    try:
        execucoes = list_recent_execucoes(limit=1)
    except Exception as exc:
        log.warning("Falha ao ler execucoes_log pro Dashboard: %s", exc)
        execucoes = []
    ultima_execucao = execucoes[0] if execucoes else None

    eventos_view = []
    for event in events:
        row = config_by_id.get(event["id"], {})
        eventos_view.append(
            {
                "id": event["id"],
                "nome": event.get("name", ""),
                "data": (event.get("start_date") or "")[:10],
                "inscritos": row.get("inscritos_count", 0),
                "presentes": row.get("presentes_count", 0),
                "ultimo_sync": row.get("ultimo_sync_em"),
                "ativo": row.get("ativo", True),
            }
        )

    return render_template(
        "dashboard.html",
        total_disponiveis=len(events),
        total_sincronizados=total_sincronizados,
        ultima_execucao=ultima_execucao,
        eventos=eventos_view,
    )
