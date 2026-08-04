"""
Gatilho HTTP pro motor de sincronização agendado — pensado pra ser chamado
por um serviço de cron externo gratuito (cron-job.org ou parecido), mesmo
papel que ele já cumpria batendo em workflow_dispatch do GitHub Actions,
agora batendo direto aqui.

Protegido por token de longa duração (SYNC_TRIGGER_TOKEN), NÃO pela sessão
de admin do painel — quem chama é um serviço externo sem navegador, não
dá pra fazer login interativo. Nunca reaproveita a trava por sessão; quem
evita duas sincronizações ao mesmo tempo é a trava 'global' já embutida
dentro de sync_all_upcoming_events() (repositories/sync_locks_repo.py).
"""

import logging
import os

from flask import Blueprint, jsonify, request

from services.lead_sync_service import sync_all_upcoming_events

log = logging.getLogger("interface.sync")

sync_bp = Blueprint("sync", __name__, url_prefix="/api/sync")

SYNC_TRIGGER_TOKEN = os.environ.get("SYNC_TRIGGER_TOKEN", "")


@sync_bp.route("/trigger", methods=["GET", "POST"])
def trigger():
    if not SYNC_TRIGGER_TOKEN:
        log.error("SYNC_TRIGGER_TOKEN não configurado no servidor — gatilho externo desabilitado.")
        return jsonify({"error": "SYNC_TRIGGER_TOKEN não configurado no servidor"}), 503

    token = request.args.get("token") or request.headers.get("X-Sync-Token", "")
    if token != SYNC_TRIGGER_TOKEN:
        return jsonify({"error": "token inválido"}), 401

    stats = sync_all_upcoming_events()
    return jsonify(stats)
