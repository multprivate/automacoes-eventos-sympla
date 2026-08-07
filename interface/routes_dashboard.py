"""
Dashboard: visão geral (eventos sincronizados — passados e futuros —,
inscritos capturados, última sincronização).
"""

import logging

from flask import Blueprint, render_template

from repositories.logs_repo import list_recent_execucoes

from .auth import login_required
from .eventos_helper import list_all_events_view

log = logging.getLogger("interface.dashboard")

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    eventos_view = list_all_events_view()
    total_sincronizados = sum(1 for e in eventos_view if e.get("ultimo_sync"))

    try:
        execucoes = list_recent_execucoes(limit=1)
    except Exception as exc:
        log.warning("Falha ao ler execucoes_log pro Dashboard: %s", exc)
        execucoes = []
    ultima_execucao = execucoes[0] if execucoes else None

    return render_template(
        "dashboard.html",
        total_disponiveis=len(eventos_view),
        total_sincronizados=total_sincronizados,
        ultima_execucao=ultima_execucao,
        eventos=eventos_view,
    )
