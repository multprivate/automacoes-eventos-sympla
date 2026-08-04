"""
Painel administrativo: Dashboard/Eventos/Mapeamento/Cupons/Logs. Processo
Flask SEPARADO de automacao_b_presenca.py — nunca registrado como
Blueprint dentro dele (diferente do que a branch abandonada
feature/interface fazia). Só importa de common/domain/services/
repositories, nunca o inverso.
"""

import logging
import os
import secrets

from flask import Flask

from .auth import auth_bp
from .routes_cupons import cupons_bp
from .routes_dashboard import dashboard_bp
from .routes_eventos import eventos_bp
from .routes_logs import logs_bp
from .routes_mapeamento import mapeamento_bp

log = logging.getLogger("interface")


def create_app() -> Flask:
    app = Flask(__name__)

    secret_key = os.environ.get("FLASK_SECRET_KEY")
    if not secret_key:
        log.warning(
            "FLASK_SECRET_KEY não configurado — usando chave aleatória só para esta "
            "execução (sessão não sobrevive a restart nem funciona com múltiplos workers)."
        )
        secret_key = secrets.token_hex(32)
    app.secret_key = secret_key

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(eventos_bp)
    app.register_blueprint(mapeamento_bp)
    app.register_blueprint(cupons_bp)
    app.register_blueprint(logs_bp)

    return app
