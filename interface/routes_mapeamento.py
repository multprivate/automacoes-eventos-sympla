"""
Aba Mapeamento: edição dos códigos de campo/estágio do Bitrix
(config_kv), com o mesmo padrão dual-read-com-fallback já usado em
Cupons. Só as chaves que services/config_service.py de fato consome
(usadas pelo motor de sincronização) aparecem aqui — FIELD_PRESENTE_NO_EVENTO
é da Automação B, que continua lendo direto do .env/secrets do próprio
serviço, e editar aqui não teria efeito nenhum sobre ela.

Também expõe os mapeamentos extras (mapeamentos_campos): vincular um dado
que o motor já extrai do participante (cupom, telefone, nome, e-mail) a
qualquer campo Bitrix, sem precisar de ajuste de código a cada campo novo
— ver domain/campo_extra_mapeamento.py.
"""

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for

from domain.campo_extra_mapeamento import ORIGENS_DISPONIVEIS
from repositories import campo_mapeamentos_repo, config_repo
from services import campo_mapeamento_service, config_service

from .auth import login_required

log = logging.getLogger("interface.mapeamento")

mapeamento_bp = Blueprint("mapeamento", __name__, url_prefix="/mapeamento")

_DESCRICOES = {
    "FIELD_DATA_DO_EVENTO": 'Código do campo customizado "Data do evento"',
    "FIELD_NOME_DO_EVENTO": 'Código do campo customizado "Nome do evento"',
    "FIELD_SYMPLA_EVENT_ID": "Código do campo customizado com o ID interno do evento Sympla",
    "FIELD_ORIGEM": 'Código do campo customizado "Origem"',
    "FIELD_FILTRAR_EVENTO": 'Código do campo customizado "Filtrar Evento"',
    "STAGE_INSCRITO_PRO_EVENTO": 'Código do estágio "Inscrito Pro Evento" no funil de Leads',
}


@mapeamento_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        chaves = request.form.getlist("chave")
        salvou_alguma = False
        for chave in chaves:
            valor = request.form.get(f"valor_{chave}", "").strip()
            if not valor:
                continue
            config_repo.upsert(chave, valor, _DESCRICOES.get(chave))
            salvou_alguma = True
        if salvou_alguma:
            config_service.load_config(force_refresh=True)
            flash("Configuração salva.", "ok")
        return redirect(url_for("mapeamento.index"))

    efetivo = config_service.load_config(force_refresh=True)
    linhas = [{"chave": chave, "valor": valor, "descricao": _DESCRICOES.get(chave, "")} for chave, valor in efetivo.items()]

    try:
        extras = campo_mapeamento_service.load_mapeamentos(force_refresh=True)
    except Exception as exc:
        log.warning("Falha ao ler mapeamentos_campos: %s", exc)
        extras = []
        flash(f"Não foi possível ler os mapeamentos extras agora: {exc}", "erro")

    return render_template(
        "mapeamento.html",
        linhas=linhas,
        extras=extras,
        origens_disponiveis=ORIGENS_DISPONIVEIS,
    )


@mapeamento_bp.route("/extras/salvar", methods=["POST"])
@login_required
def extras_salvar():
    origem_dado = request.form.get("origem_dado", "")
    bitrix_field_code = request.form.get("bitrix_field_code", "").strip()
    aplicar_em = request.form.get("aplicar_em", "")

    if origem_dado not in ORIGENS_DISPONIVEIS:
        flash("Escolhe uma origem de dado válida.", "erro")
        return redirect(url_for("mapeamento.index"))
    if not bitrix_field_code:
        flash("Preenche o código do campo Bitrix (ex: UF_CRM_...).", "erro")
        return redirect(url_for("mapeamento.index"))
    if aplicar_em not in ("novo", "todos"):
        flash("Escolhe se aplica só em Leads novos ou em todos.", "erro")
        return redirect(url_for("mapeamento.index"))

    campo_mapeamentos_repo.create(origem_dado, bitrix_field_code, aplicar_em)
    campo_mapeamento_service.load_mapeamentos(force_refresh=True)
    flash(f"Mapeamento '{ORIGENS_DISPONIVEIS[origem_dado]}' → {bitrix_field_code} salvo.", "ok")
    return redirect(url_for("mapeamento.index"))


@mapeamento_bp.route("/extras/remover", methods=["POST"])
@login_required
def extras_remover():
    mapeamento_id = request.form.get("id", "")
    if mapeamento_id:
        campo_mapeamentos_repo.delete(mapeamento_id)
        campo_mapeamento_service.load_mapeamentos(force_refresh=True)
        flash("Mapeamento removido.", "ok")
    return redirect(url_for("mapeamento.index"))
