"""
Aba "Verificação de Duplicados": lista os pares de Lead que a varredura
periódica de telefone (services/duplicidade_service.py) encontrou, com
link direto pros dois cards no Bitrix e os botões Mesclar/Ignorar — a
decisão de mesclar é sempre humana, o código nunca mescla sozinho.
"""

import logging

from flask import Blueprint, flash, redirect, render_template, url_for

from repositories import duplicados_repo
from services.duplicidade_service import executar_merge, ignorar

from .auth import login_required
from .bitrix_links import lead_url as _lead_url

log = logging.getLogger("interface.duplicados")

duplicados_bp = Blueprint("duplicados", __name__, url_prefix="/duplicados")


@duplicados_bp.route("/")
@login_required
def index():
    try:
        pendentes = duplicados_repo.get_pendentes()
    except Exception as exc:
        log.warning("Falha ao ler duplicados_candidatos: %s", exc)
        flash(f"Não foi possível carregar os candidatos a duplicado: {exc}", "erro")
        pendentes = []

    for row in pendentes:
        row["url_a"] = _lead_url(row["lead_id_a"])
        row["url_b"] = _lead_url(row["lead_id_b"])

    return render_template("duplicados.html", candidatos=pendentes)


@duplicados_bp.route("/<candidato_id>/mesclar", methods=["POST"])
@login_required
def mesclar(candidato_id):
    try:
        resultado = executar_merge(candidato_id)
        flash(f"Lead {resultado['secondary_id']} mesclado em {resultado['primary_id']} com sucesso.", "ok")
    except Exception as exc:
        log.error("Falha ao mesclar candidato %s: %s", candidato_id, exc)
        flash(f"Falha ao mesclar: {exc}", "erro")
    return redirect(url_for("duplicados.index"))


@duplicados_bp.route("/<candidato_id>/ignorar", methods=["POST"])
@login_required
def ignorar_rota(candidato_id):
    try:
        ignorar(candidato_id)
        flash("Candidato marcado como ignorado.", "ok")
    except Exception as exc:
        log.error("Falha ao ignorar candidato %s: %s", candidato_id, exc)
        flash(f"Falha ao ignorar: {exc}", "erro")
    return redirect(url_for("duplicados.index"))
