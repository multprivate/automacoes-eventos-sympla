"""
Endpoint leve pro ping de keep-alive (cron-job.org/UptimeRobot) do painel —
espelha automacao_b_presenca.py's /health. Não chama Supabase/Bitrix/Sympla,
só confirma que o processo está de pé. Sem @login_required de propósito:
um cron externo não manda cookie de sessão, então herdar o decorator faria
o ping sempre cair no redirect pro login (302) em vez de 200.
"""

from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200
