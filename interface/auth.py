"""
Autenticação do painel: sessão por senha única (ADMIN_PASSWORD), assinada
com FLASK_SECRET_KEY. Sem tabela de usuários — evolução futura se o time
crescer além de "senha compartilhada".
"""

import hmac
import os
from functools import wraps

from dotenv import load_dotenv
from flask import Blueprint, redirect, render_template, request, session, url_for

load_dotenv()

auth_bp = Blueprint("auth", __name__)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logado"):
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    erro = None
    if request.method == "POST":
        senha = request.form.get("senha", "")
        if not ADMIN_PASSWORD:
            erro = "ADMIN_PASSWORD não configurado no servidor — fala com quem administra o deploy."
        elif hmac.compare_digest(senha, ADMIN_PASSWORD):
            session["admin_logado"] = True
            destino = request.args.get("next") or url_for("dashboard.index")
            return redirect(destino)
        else:
            erro = "Senha incorreta."
    return render_template("login.html", erro=erro)


@auth_bp.route("/logout")
def logout():
    session.pop("admin_logado", None)
    return redirect(url_for("auth.login"))
