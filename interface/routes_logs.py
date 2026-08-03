"""
Aba Logs: histórico paginado de execucoes_log_itens, com filtro por
entidade (Todas/Evento/Participante — hoje só há entradas 'evento', já
que o log fino foi escopado a esse nível nesta fase; granularidade por
participante fica pra uma iteração futura se o time sentir falta).
"""

import logging

from flask import Blueprint, render_template, request

from repositories import logs_repo

from .auth import login_required

log = logging.getLogger("interface.logs")

logs_bp = Blueprint("logs", __name__, url_prefix="/logs")


@logs_bp.route("/")
@login_required
def index():
    tipo = request.args.get("tipo") or None
    page = max(int(request.args.get("page", 1)), 1)
    try:
        itens = logs_repo.list_itens(entidade_tipo=tipo, page=page)
    except Exception as exc:
        log.warning("Falha ao ler execucoes_log_itens: %s", exc)
        itens = []

    # Estatísticas calculadas só sobre a página atual (não um agregado
    # global) — evita ter que buscar a tabela inteira só pra somar.
    sucessos = sum(1 for i in itens if i.get("status") == "ok")
    erros = sum(1 for i in itens if i.get("status") == "error")
    duracoes = [i["duracao_ms"] for i in itens if i.get("duracao_ms") is not None]
    tempo_medio_ms = round(sum(duracoes) / len(duracoes)) if duracoes else 0

    return render_template(
        "logs.html",
        itens=itens,
        tipo_atual=tipo or "todas",
        page=page,
        sucessos=sucessos,
        erros=erros,
        tempo_medio_ms=tempo_medio_ms,
    )
