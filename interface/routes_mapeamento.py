"""
Aba Mapeamento: edição dos códigos de campo/estágio do Bitrix
(config_kv), com o mesmo padrão dual-read-com-fallback já usado em
Cupons. Só as chaves que services/config_service.py de fato consome
(usadas pelo motor de sincronização) aparecem aqui — FIELD_PRESENTE_NO_EVENTO
é da Automação B, que continua lendo direto do .env/secrets do próprio
serviço, e editar aqui não teria efeito nenhum sobre ela.
"""

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for

from repositories import config_repo
from services import config_service

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
    return render_template("mapeamento.html", linhas=linhas)
