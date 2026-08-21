"""
Aba Eventos: junta todo evento já sincronizado (passado ou futuro) com
eventos_config (contadores, ativo/removido) e expõe as 3 ações —
Sincronizar agora, Forçar atualização de campos, Remover — mais o toggle
Ativo/Inativo.
"""

import logging
import math

from flask import Blueprint, flash, redirect, render_template, request, url_for

from common import get_sympla_all_participants
from repositories import eventos_config_repo, processed_repo
from repositories.sync_locks_repo import SyncLockHeld, acquire_lock, release_lock
from services.lead_sync_service import (
    find_or_create_evento_item,
    get_event_or_raise,
    new_stats,
    preparar_contexto_evento,
    process_participant,
    sync_one_event,
)

from .auth import login_required
from .bitrix_links import contact_url, lead_url
from .eventos_helper import list_all_events_view
from .inscritos_helper import build_inscritos_view, resumo_conversao

log = logging.getLogger("interface.eventos")

eventos_bp = Blueprint("eventos", __name__, url_prefix="/eventos")

INSCRITOS_PAGE_SIZE = 50


def _config_by_id() -> dict[str, dict]:
    try:
        return {row["sympla_event_id"]: row for row in eventos_config_repo.get_all()}
    except Exception as exc:
        log.warning("Falha ao ler eventos_config: %s", exc)
        return {}


@eventos_bp.route("/")
@login_required
def index():
    return render_template("eventos.html", eventos=list_all_events_view())


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


@eventos_bp.route("/<event_id>/inscritos")
@login_required
def inscritos(event_id):
    """Lista todo inscrito do evento: id na Sympla, se já era cliente
    (Contato) no Bitrix e por qual sinal, e quando foi encontrado.

    Nome/e-mail/telefone/CPF/check-in vêm AO VIVO da Sympla a cada
    visita — mesmo custo que a sincronização já paga a cada rodada
    (get_sympla_all_participants pagina a lista inteira, ~0.3s por
    página), sem armazenamento novo. "Cliente ou não" vem de
    participantes_processados (persistido no momento da sincronização —
    migração 0006), não recalculado aqui.

    Paginação em memória (não Supabase offset/limit): a lista inteira já
    precisa vir da Sympla mesmo pro cálculo da taxa de conversão."""
    try:
        event = get_event_or_raise(event_id)
    except ValueError as exc:
        flash(str(exc), "erro")
        return redirect(url_for("eventos.index"))

    try:
        participants = get_sympla_all_participants(event_id)
    except Exception as exc:
        log.warning("Falha ao buscar participantes de %s na Sympla: %s", event_id, exc)
        flash(f"Não foi possível buscar os inscritos na Sympla: {exc}", "erro")
        participants = []

    try:
        resultados = processed_repo.get_resultados(event_id)
    except Exception as exc:
        log.warning("Falha ao ler participantes_processados de %s: %s", event_id, exc)
        flash("Não foi possível ler o resultado da sincronização — todo mundo aparece como 'não verificado'.", "erro")
        resultados = {}

    linhas = build_inscritos_view(participants, resultados)
    for linha in linhas:
        if linha["contact_id"]:
            linha["contact_url"] = contact_url(linha["contact_id"])
        if linha["lead_id"]:
            linha["lead_url"] = lead_url(linha["lead_id"])
        if linha["contact_ids_duplicados"]:
            linha["contact_urls_duplicados"] = [contact_url(cid) for cid in linha["contact_ids_duplicados"]]

    resumo = resumo_conversao(linhas)

    page = max(int(request.args.get("page", 1)), 1)
    total_paginas = max(1, math.ceil(len(linhas) / INSCRITOS_PAGE_SIZE))
    page = min(page, total_paginas)
    pagina = linhas[(page - 1) * INSCRITOS_PAGE_SIZE : page * INSCRITOS_PAGE_SIZE]

    evento_view = {
        "id": event_id,
        "nome": event.get("name", ""),
        "data": (event.get("start_date") or "")[:10],
    }
    return render_template(
        "evento_detalhe.html", evento=evento_view, linhas=pagina, resumo=resumo,
        page=page, total_paginas=total_paginas, total=len(linhas),
    )


@eventos_bp.route("/<event_id>/inscritos/<participant_id>/reprocessar", methods=["POST"])
@login_required
def reprocessar_inscrito(event_id, participant_id):
    """Refaz o match de UM inscrito (mesma cascata CPF→telefone→e-mail→nome
    de sempre) e atualiza o card dele no Bitrix — força leve (force=False):
    reconfere, não reenvia campo que já está certo nem move estágio. Pra
    isso, "Forçar atualização de campos" (por evento inteiro) já existe.

    Recusa rodar se o item da SPA "Eventos Sympla" estiver indisponível
    (item_id None): esta rota está SEMPRE reprocessando alguém que já foi
    processado antes — diferente do fluxo normal (só processa quem ainda
    não tem marca), aqui item_id=None faria um cliente ganhar um Lead
    duplicado pro mesmo evento (contact_needs_new_event_lead não acha o
    Lead já vinculado porque a busca depende do item_id). Bug pré-existente
    no motor, não introduzido por esta rota — só evitado aqui."""
    page = request.form.get("page", "1")
    redirect_url = url_for("eventos.inscritos", event_id=event_id, page=page)

    try:
        acquire_lock(event_id, "painel")
    except SyncLockHeld as exc:
        flash(f"Evento {event_id}: {exc}", "erro")
        return redirect(redirect_url)

    try:
        try:
            event = get_event_or_raise(event_id)
            participants = get_sympla_all_participants(event_id)
        except Exception as exc:
            flash(f"Falha ao buscar dados do evento/inscrito: {exc}", "erro")
            return redirect(redirect_url)

        participant = next((p for p in participants if str(p.get("id")) == str(participant_id)), None)
        if participant is None:
            flash(f"Inscrito {participant_id} não encontrado na lista atual de participantes.", "erro")
            return redirect(redirect_url)

        event_name = event.get("name", "")
        event_date = (event.get("start_date") or "")[:10]
        presentes_count = sum(1 for p in participants if (p.get("checkin") or {}).get("check_in_date"))
        item_id = find_or_create_evento_item(event_id, event_name, event_date, len(participants), presentes_count)
        if item_id is None:
            flash("SPA 'Eventos Sympla' indisponível no Bitrix agora — reprocessar poderia criar um Lead duplicado pra este cliente. Tente de novo em instantes.", "erro")
            return redirect(redirect_url)

        ctx = preparar_contexto_evento(event_id, event_name, event_date)
        stats = new_stats()
        resultado = process_participant(
            participant, event_name, event_date, event_id, ctx["filtrar_evento_id"], ctx["get_cupom_map"],
            stats, ctx["field_config"], ctx["extra_mapeamentos"], item_id=item_id, force=False,
            event_already_happened=ctx["event_already_happened"],
        )

        if resultado is None:
            flash(f"Falha ao reprocessar o inscrito {participant_id} — veja a aba Logs.", "erro")
            return redirect(redirect_url)

        try:
            processed_repo.mark_processed_batch(event_id, [resultado])
        except Exception as exc:
            log.warning("Falha ao gravar resultado do reprocessamento de %s/%s: %s", event_id, participant_id, exc)
            flash("Inscrito reprocessado no Bitrix, mas falhou ao salvar o resultado — tente reprocessar de novo.", "erro")
            return redirect(redirect_url)

        rotulo_cliente = "cliente" if resultado["is_cliente"] else "prospect"
        flash(f"Inscrito {participant_id} reprocessado ({rotulo_cliente}, match: {resultado['match_method'] or '—'}).", "ok")
        return redirect(redirect_url)
    finally:
        release_lock(event_id)
