"""
Aba Cupons: CRUD sobre assessores_cupom, por cima do
services/coupon_service.py + repositories/coupons_repo.py já existentes
(Fase 2) — só faltava a camada HTTP.
"""

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for

from repositories import coupons_repo
from services import coupon_service

from .auth import login_required

log = logging.getLogger("interface.cupons")

cupons_bp = Blueprint("cupons", __name__, url_prefix="/cupons")


@cupons_bp.route("/")
@login_required
def index():
    try:
        rows = coupons_repo.list_coupons()
    except Exception as exc:
        log.warning("Falha ao ler assessores_cupom: %s", exc)
        rows = []
        flash(f"Não foi possível ler os cupons do Supabase agora: {exc}", "erro")
    rows = sorted(rows, key=lambda r: r.get("cupom", ""))

    editando = None
    cupom_editar = request.args.get("editar", "")
    if cupom_editar:
        editando = next((r for r in rows if r.get("cupom") == cupom_editar), None)
        if editando is None:
            flash(f"Cupom '{cupom_editar}' não encontrado — pode já ter sido removido.", "erro")

    return render_template("cupons.html", cupons=rows, editando=editando)


@cupons_bp.route("/salvar", methods=["POST"])
@login_required
def salvar():
    cupom = request.form.get("cupom", "").strip().upper()
    cupom_original = request.form.get("cupom_original", "").strip()
    tipo = request.form.get("tipo", "")
    email_assessor = request.form.get("email_assessor", "").strip() or None
    origem_canal = request.form.get("origem_canal", "").strip() or None

    if not cupom or tipo not in ("assessor", "canal"):
        flash("Preenche cupom e tipo pra salvar.", "erro")
        return redirect(url_for("cupons.index"))
    if tipo == "assessor" and not email_assessor:
        flash("Tipo 'assessor' precisa do e-mail do assessor.", "erro")
        return redirect(url_for("cupons.index"))
    if tipo == "canal" and not origem_canal:
        flash("Tipo 'canal' precisa do texto da Origem.", "erro")
        return redirect(url_for("cupons.index"))

    try:
        if cupom_original and cupom_original != cupom:
            # Editando um cupom já existente e o texto mudou: renomeia de
            # verdade (muda a chave primária) em vez de upsert, que
            # deixaria a linha antiga órfã pra trás com o cupom_original.
            coupons_repo.rename_and_update_coupon(cupom_original, cupom, tipo, email_assessor, origem_canal)
        else:
            coupons_repo.upsert_coupon(cupom, tipo, email_assessor, origem_canal)
    except Exception as exc:
        log.error("Falha ao salvar cupom '%s' (original: '%s'): %s", cupom, cupom_original, exc)
        flash(f"Falha ao salvar o cupom '{cupom}' — já existe outro cupom com esse texto? Detalhe: {exc}", "erro")
        return redirect(url_for("cupons.index"))

    coupon_service.load_coupon_maps(force_refresh=True)
    flash(f"Cupom '{cupom}' salvo.", "ok")
    return redirect(url_for("cupons.index"))


@cupons_bp.route("/remover", methods=["POST"])
@login_required
def remover():
    cupom = request.form.get("cupom", "")
    if cupom:
        coupons_repo.delete_coupon(cupom)
        coupon_service.load_coupon_maps(force_refresh=True)
        flash(f"Cupom '{cupom}' removido.", "ok")
    return redirect(url_for("cupons.index"))
