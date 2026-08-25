"""
Aba Eventos: junta todo evento já sincronizado (passado ou futuro) com
eventos_config (contadores, ativo/removido) e expõe as 3 ações —
Sincronizar agora, Forçar atualização de campos, Remover — mais o toggle
Ativo/Inativo.
"""

import csv
import io
import logging
import math

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from common import find_leads_by_evento_item, get_sympla_all_participants, spa_find_item_by_sympla_event_id
from domain.funil_conversao import classificar_lead, resumo_funil
from repositories import eventos_config_repo, processed_repo
from repositories.sync_locks_repo import SyncLockHeld, acquire_lock, release_lock
from services import config_service
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
from .inscritos_helper import build_inscritos_view, filter_linhas, montar_funil_barras, resumo_conversao

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
            flash(f"Sincronização de {event_id} terminou com {result['erros']} erro(s). Veja a aba Logs.", "erro")
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


_ETAPA_ROTULOS = {
    "inscrito": "Inscrito pro evento",
    "pos_evento": "Pós Evento",
    "reuniao": "Reunião marcada",
    "convertido": "Negócio gerado",
    "perdido": "Perdido (Lead Perdido)",
    "fora_do_funil": "Fora do funil novo",
}


def _montar_dados_evento(event_id: str) -> tuple[dict, list[dict], dict | None]:
    """Busca tudo que a aba Inscritos precisa: o evento, os participantes
    ao vivo da Sympla juntados com o resultado do match persistido
    (build_inscritos_view), e o funil de conversão (Leads vinculados ao
    item da SPA "Eventos Sympla" — domain/funil_conversao.py). A MESMA
    busca de Leads alimenta o resumo agregado (funil) E a etapa individual
    de cada linha (linha["etapa_bucket"]/["etapa_rotulo"], usados pelo
    filtro ?etapa=) — uma chamada só ao Bitrix, não duas. Reusado pela tela
    (GET /inscritos) e pela exportação CSV, pra não duplicar busca+join+
    funil em dois lugares.

    Levanta ValueError se o evento não existir na Sympla (via
    get_event_or_raise) — quem chama decide o redirect. As outras leituras
    falham ABERTO (flash de aviso, segue com dado parcial): perder o funil
    ou o resultado do match não deveria impedir de ver a lista de
    inscritos.

    Usa spa_find_item_by_sympla_event_id (busca READ-ONLY) pro funil, não
    find_or_create_evento_item — essa página só lê, não deveria ter o
    efeito colateral de criar/atualizar o item da SPA a cada visita."""
    event = get_event_or_raise(event_id)

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
        flash("Não foi possível ler o resultado da sincronização: todo mundo aparece como 'não verificado'.", "erro")
        resultados = {}

    linhas = build_inscritos_view(participants, resultados)
    for linha in linhas:
        if linha["contact_id"]:
            linha["contact_url"] = contact_url(linha["contact_id"])
        if linha["lead_id"]:
            linha["lead_url"] = lead_url(linha["lead_id"])
        if linha["contact_ids_duplicados"]:
            linha["contact_urls_duplicados"] = [contact_url(cid) for cid in linha["contact_ids_duplicados"]]
        linha["etapa_bucket"] = None
        linha["etapa_rotulo"] = None

    funil = None
    try:
        item = spa_find_item_by_sympla_event_id(event_id)
        if item:
            leads = find_leads_by_evento_item(int(item["id"]))
            stage_inscrito = config_service.get_stage_inscrito_pro_evento()
            stage_pos_evento = config_service.get_stage_pos_evento()
            stage_reuniao = config_service.get_stage_reuniao()

            funil = resumo_funil(leads, stage_inscrito, stage_pos_evento, stage_reuniao)

            status_by_lead_id = {str(l["ID"]): l.get("STATUS_ID") for l in leads}
            for linha in linhas:
                status_id = status_by_lead_id.get(str(linha["lead_id"])) if linha["lead_id"] else None
                if status_id is not None:
                    bucket = classificar_lead(status_id, stage_inscrito, stage_pos_evento, stage_reuniao)
                    linha["etapa_bucket"] = bucket
                    linha["etapa_rotulo"] = _ETAPA_ROTULOS[bucket]
    except Exception as exc:
        log.warning("Falha ao montar funil de conversão de %s: %s", event_id, exc)

    evento_view = {
        "id": event_id,
        "nome": event.get("name", ""),
        "data": (event.get("start_date") or "")[:10],
    }
    return evento_view, linhas, funil


@eventos_bp.route("/<event_id>/inscritos")
@login_required
def inscritos(event_id):
    """Lista todo inscrito do evento: id na Sympla, se já era cliente
    (Contato) no Bitrix e por qual sinal, quando foi encontrado, e o
    funil de conversão (Inscrito → Pós Evento → Reunião → Negócio).

    Nome/e-mail/telefone/CPF/check-in vêm AO VIVO da Sympla a cada
    visita — mesmo custo que a sincronização já paga a cada rodada
    (get_sympla_all_participants pagina a lista inteira, ~0.3s por
    página), sem armazenamento novo. "Cliente ou não" vem de
    participantes_processados (persistido no momento da sincronização —
    migração 0006), não recalculado aqui.

    ?q=/?status=/?etapa= filtram a LISTAGEM (interface/inscritos_helper.py::
    filter_linhas) — o resumo/funil continuam sobre o evento inteiro, pra
    filtrar não dar a impressão de que a taxa de conversão mudou. etapa é
    o bucket do funil do Lead vinculado (inscrito/pos_evento/reuniao/
    convertido/perdido/fora_do_funil), independente de status (cliente/
    prospect/não verificado): um inscrito pode ser cliente com o Lead em
    qualquer etapa.

    Paginação em memória (não Supabase offset/limit): a lista inteira já
    precisa vir da Sympla mesmo pro cálculo da taxa de conversão."""
    try:
        evento_view, linhas, funil = _montar_dados_evento(event_id)
    except ValueError as exc:
        flash(str(exc), "erro")
        return redirect(url_for("eventos.index"))

    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    etapa = request.args.get("etapa", "")
    linhas_filtradas = filter_linhas(linhas, q=q, status=status, etapa=etapa)

    resumo = resumo_conversao(linhas)

    page = max(int(request.args.get("page", 1)), 1)
    total_paginas = max(1, math.ceil(len(linhas_filtradas) / INSCRITOS_PAGE_SIZE))
    page = min(page, total_paginas)
    pagina = linhas_filtradas[(page - 1) * INSCRITOS_PAGE_SIZE : page * INSCRITOS_PAGE_SIZE]

    return render_template(
        "evento_detalhe.html", evento=evento_view, linhas=pagina, resumo=resumo,
        funil=funil, funil_barras=montar_funil_barras(funil), etapa_rotulos=_ETAPA_ROTULOS,
        page=page, total_paginas=total_paginas, total=len(linhas_filtradas), total_geral=len(linhas),
        q=q, status=status, etapa=etapa,
    )


@eventos_bp.route("/<event_id>/inscritos/exportar.csv")
@login_required
def exportar_inscritos_csv(event_id):
    """Exporta em CSV exatamente o que a tela de Inscritos está mostrando
    (respeita ?q=/?status=/?etapa=, sem paginação) — colunas alinhadas com
    interface/inscritos_helper.py::build_inscritos_view. BOM UTF-8 no
    início pra abrir certo no Excel (que sem isso interpreta como
    Latin-1 e quebra acentuação)."""
    try:
        _, linhas, _ = _montar_dados_evento(event_id)
    except ValueError as exc:
        flash(str(exc), "erro")
        return redirect(url_for("eventos.index"))

    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    etapa = request.args.get("etapa", "")
    linhas_filtradas = filter_linhas(linhas, q=q, status=status, etapa=etapa)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["participant_id", "nome", "email", "telefone", "cpf", "status", "match_method", "etapa_lead", "encontrado_em", "verificado_em", "contact_id", "lead_id", "checkin"])
    for l in linhas_filtradas:
        writer.writerow([
            l["participant_id"], l["nome"], l["email"], l["telefone"], l["cpf"], l["status"],
            l["match_method"] or "", l["etapa_rotulo"] or "", l["processado_em"] or "", l["verificado_em"] or "",
            l["contact_id"] or "", l["lead_id"] or "", "sim" if l["checkin"] else "não",
        ])

    resposta = Response("﻿" + buffer.getvalue(), content_type="text/csv; charset=utf-8")
    resposta.headers["Content-Disposition"] = f"attachment; filename=inscritos_{event_id}.csv"
    return resposta


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
    q = request.form.get("q", "")
    status = request.form.get("status", "")
    etapa = request.form.get("etapa", "")
    redirect_url = url_for("eventos.inscritos", event_id=event_id, page=page, q=q, status=status, etapa=etapa)

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
            flash("SPA 'Eventos Sympla' indisponível no Bitrix agora: reprocessar poderia criar um Lead duplicado pra este cliente. Tente de novo em instantes.", "erro")
            return redirect(redirect_url)

        ctx = preparar_contexto_evento(event_id, event_name, event_date)
        stats = new_stats()
        resultado = process_participant(
            participant, event_name, event_date, event_id, ctx["filtrar_evento_id"], ctx["get_cupom_map"],
            stats, ctx["field_config"], ctx["extra_mapeamentos"], item_id=item_id, force=False,
            event_already_happened=ctx["event_already_happened"],
        )

        if resultado is None:
            flash(f"Falha ao reprocessar o inscrito {participant_id}. Veja a aba Logs.", "erro")
            return redirect(redirect_url)

        try:
            processed_repo.mark_processed_batch(event_id, [resultado])
        except Exception as exc:
            log.warning("Falha ao gravar resultado do reprocessamento de %s/%s: %s", event_id, participant_id, exc)
            flash("Inscrito reprocessado no Bitrix, mas falhou ao salvar o resultado. Tente reprocessar de novo.", "erro")
            return redirect(redirect_url)

        rotulo_cliente = "cliente" if resultado["is_cliente"] else "prospect"
        flash(f"Inscrito {participant_id} reprocessado ({rotulo_cliente}, match: {resultado['match_method'] or '–'}).", "ok")
        return redirect(redirect_url)
    finally:
        release_lock(event_id)
