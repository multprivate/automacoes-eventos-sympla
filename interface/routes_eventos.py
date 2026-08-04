"""
Aba Eventos: junta eventos futuros da Sympla com eventos_config
(contadores, ativo/removido) e expõe as 3 ações — Sincronizar agora,
Forçar atualização de campos, Remover — mais o toggle Ativo/Inativo.
"""

import logging

from flask import Blueprint, flash, redirect, render_template, url_for

from common import list_upcoming_events
from repositories import eventos_config_repo
from repositories.sync_locks_repo import SyncLockHeld, acquire_lock, release_lock
from services.lead_sync_service import sync_one_event

from .auth import login_required

log = logging.getLogger("interface.eventos")

eventos_bp = Blueprint("eventos", __name__, url_prefix="/eventos")


def _config_by_id() -> dict[str, dict]:
    try:
        return {row["sympla_event_id"]: row for row in eventos_config_repo.get_all()}
    except Exception as exc:
        log.warning("Falha ao ler eventos_config: %s", exc)
        return {}


def _eventos_view() -> list[dict]:
    events = list_upcoming_events()
    config_by_id = _config_by_id()

    view = []
    for event in events:
        row = config_by_id.get(event["id"], {})
        view.append(
            {
                "id": event["id"],
                "nome": event.get("name", ""),
                "data": (event.get("start_date") or "")[:10],
                "inscritos": row.get("inscritos_count", 0),
                "presentes": row.get("presentes_count", 0),
                "ultimo_sync": row.get("ultimo_sync_em"),
                "ativo": row.get("ativo", True),
                "removido": bool(row.get("removido_em")),
            }
        )
    return view


@eventos_bp.route("/")
@login_required
def index():
    return render_template("eventos.html", eventos=_eventos_view())


def _run_sync(event_id: str, force: bool) -> None:
    try:
        acquire_lock(event_id, "painel")
    except SyncLockHeld as exc:
        flash(f"Evento {event_id}: {exc}", "erro")
        return
    try:
        result = sync_one_event(event_id, force=force)
        if result["erros"]:
            flash(f"Sincronização de {event_id} terminou com {result['erros']} erro(s) — veja a aba Logs.", "erro")
        else:
            flash(f"Evento {event_id} sincronizado: {result['leads_criados']} lead(s) criado(s), {result['leads_atualizados']} atualizado(s).", "ok")
    except Exception as exc:
        log.error("Falha ao sincronizar evento %s: %s", event_id, exc)
        flash(f"Falha ao sincronizar {event_id}: {exc}", "erro")
    finally:
        release_lock(event_id)


@eventos_bp.route("/<event_id>/sincronizar", methods=["POST"])
@login_required
def sincronizar(event_id):
    _run_sync(event_id, force=False)
    return redirect(url_for("eventos.index"))


@eventos_bp.route("/<event_id>/forcar", methods=["POST"])
@login_required
def forcar(event_id):
    _run_sync(event_id, force=True)
    return redirect(url_for("eventos.index"))


@eventos_bp.route("/<event_id>/remover", methods=["POST"])
@login_required
def remover(event_id):
    eventos_config_repo.set_removido(event_id, True)
    flash(f"Evento {event_id} removido da sincronização automática.", "ok")
    return redirect(url_for("eventos.index"))


@eventos_bp.route("/<event_id>/toggle", methods=["POST"])
@login_required
def toggle(event_id):
    atual = _config_by_id().get(event_id, {}).get("ativo", True)
    eventos_config_repo.set_ativo(event_id, not atual)
    flash(f"Evento {event_id} agora está {'ativo' if not atual else 'inativo'}.", "ok")
    return redirect(url_for("eventos.index"))
