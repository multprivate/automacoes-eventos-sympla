"""
Automação B: exposta como um endpoint HTTP que o Bitrix24 chama (via um
Robô/Regra de automação configurado na etapa "Pós evento" — veja o
README/plano pra instruções de como configurar isso na tela do Bitrix).

Recebe o ID do Lead, descobre em qual evento da Sympla ele se inscreveu
(campo técnico UF_CRM_SYMPLA_EVENT_ID, preenchido pela Automação A) e
preenche "Presente no evento": "Presente" se achar o participante com
check-in feito, "Não Presente" se achar o participante mas sem check-in.
Só deixa o campo em branco se nem achar o participante na lista de
inscritos do evento (aí não dá pra afirmar nada com confiança).

Uso local pra teste:
    flask --app automacao_b_presenca run --port 5001
    curl -X POST http://localhost:5001/webhook/pos-evento -d "lead_id=256"
"""

import logging

from flask import Flask, request, jsonify

from common import (
    bitrix_call,
    extract_phone,
    format_phone_br,
    get_lead,
    get_sympla_all_participants,
    normalize_email,
    normalize_name,
    participant_full_name,
    resolve_enum_id,
    FIELD_PRESENTE_NO_EVENTO,
    FIELD_SYMPLA_EVENT_ID,
    VALOR_NAO_PRESENTE,
    VALOR_PRESENTE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("automacao_b_presenca")

app = Flask(__name__)


def lead_phone(lead: dict) -> str:
    phones = lead.get("PHONE") or []
    return format_phone_br(phones[0].get("VALUE", "")) if phones else ""


def lead_email(lead: dict) -> str:
    emails = lead.get("EMAIL") or []
    return normalize_email(emails[0].get("VALUE", "")) if emails else ""


def find_matching_participant(sympla_event_id: str, phone_key: str, name_key: str, email_key: str) -> dict | None:
    """Acha o participante por telefone, nome ou e-mail, independente de
    ter feito check-in ou não — quem decide o que fazer com o check-in é
    process_lead. E-mail entrou porque alguns Leads só foram casados pela
    Automação A por e-mail (telefone do Bitrix não bate com o da Sympla,
    ou vazio) — sem esse critério aqui, esses ficavam sempre "não
    encontrado", mesmo com o inscrito certinho na lista."""
    for participant in get_sympla_all_participants(sympla_event_id):
        phone_match = phone_key and format_phone_br(extract_phone(participant)) == phone_key
        name_match = name_key and normalize_name(participant_full_name(participant)) == name_key
        email_match = email_key and normalize_email(participant.get("email") or "") == email_key
        if phone_match or name_match or email_match:
            return participant
    return None


def process_lead(lead_id: str) -> dict:
    lead = get_lead(lead_id)

    sympla_event_id = lead.get(FIELD_SYMPLA_EVENT_ID)
    if not sympla_event_id:
        return {"status": "skipped", "reason": "lead sem UF_CRM_SYMPLA_EVENT_ID preenchido"}

    phone_key = lead_phone(lead)
    name_key = normalize_name(lead.get("NAME", ""))
    email_key = lead_email(lead)

    participant = find_matching_participant(sympla_event_id, phone_key, name_key, email_key)
    if not participant:
        return {"status": "not_found", "reason": "participante não encontrado na lista de inscritos do evento"}

    checked_in = bool((participant.get("checkin") or {}).get("check_in_date"))
    valor_texto = VALOR_PRESENTE if checked_in else VALOR_NAO_PRESENTE
    valor_id = resolve_enum_id(FIELD_PRESENTE_NO_EVENTO, valor_texto)

    if lead.get(FIELD_PRESENTE_NO_EVENTO) == valor_id:
        return {"status": "skipped", "reason": "campo já estava correto", "valor": valor_texto}

    bitrix_call("crm.lead.update", {"id": lead_id, "fields": {FIELD_PRESENTE_NO_EVENTO: valor_id}})
    return {"status": "updated", "participant_id": participant.get("id"), "valor": valor_texto}


@app.route("/health", methods=["GET"])
def health():
    """Endpoint leve pro ping de keep-alive (cron-job.org/UptimeRobot) —
    não chama Sympla nem Bitrix, só confirma que o serviço está de pé."""
    return jsonify({"status": "ok"}), 200


@app.route("/webhook/pos-evento", methods=["GET", "POST"])
def webhook_pos_evento():
    lead_id = request.values.get("lead_id") or request.values.get("id") or request.values.get("document_id")
    if not lead_id:
        return jsonify({"status": "error", "reason": "lead_id não informado"}), 400

    try:
        result = process_lead(lead_id)
        log.info("Lead %s: %s", lead_id, result)
        return jsonify(result), 200
    except Exception as exc:
        log.error("Falha ao processar lead %s: %s", lead_id, exc)
        return jsonify({"status": "error", "reason": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
