"""
Código compartilhado entre as duas automações (inscrição e presença):
chamadas à API do Bitrix24, chamadas à API da Sympla, e as funções de
normalização/matching usadas pelas duas pontas.
"""

import logging
import os
import re
import unicodedata
import requests
from time import sleep
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("common")

SYMPLA_TOKEN = os.environ["SYMPLA_TOKEN"]
BITRIX_WEBHOOK_URL = os.environ["BITRIX_WEBHOOK_URL"].rstrip("/")

SYMPLA_BASE = "https://api.sympla.com.br/public/v1.5.1"

STAGE_INSCRITO_PRO_EVENTO = os.environ.get("BITRIX_STAGE_INSCRITO_PRO_EVENTO", "UC_2CK7JY")
STAGES_SAFE_TO_ADVANCE = {"NEWLEAD", "NEWFUP"}

# Estágios do funil antigo (pré-reformulação do pipeline) — um Lead nesses
# estágios pode ganhar os campos de evento (Data/Nome/ID Sympla) quando
# bate uma inscrição nova, pra dar visibilidade, mas o STATUS_ID nunca
# muda: a automação não "promove" ninguém de volta pro funil novo sozinha.
# Note que UC_TJ9FPC ("Reunião") NÃO entra aqui apesar de não ter o
# prefixo [NEW]: é do funil novo.
OLD_FUNNEL_STAGES = {"NEW", "IN_PROCESS", "PROCESSED", "UC_DQZKWD", "UC_PFVCRN", "UC_Z0M384", "UC_VL3WIF"}

FIELD_DATA_DO_EVENTO = os.environ.get("BITRIX_FIELD_DATA_DO_EVENTO", "")
FIELD_NOME_DO_EVENTO = os.environ.get("BITRIX_FIELD_NOME_DO_EVENTO", "")
FIELD_SYMPLA_EVENT_ID = os.environ.get("BITRIX_FIELD_SYMPLA_EVENT_ID", "")
FIELD_ORIGEM = os.environ.get("BITRIX_FIELD_ORIGEM", "")
FIELD_PRESENTE_NO_EVENTO = os.environ.get("BITRIX_FIELD_PRESENTE_NO_EVENTO", "")

ORIGEM_VALOR_FORMULARIO = "Formulario"                            # texto; o ID é resolvido em runtime via resolve_enum_id
ORIGEM_VALOR_INSCRITO_DESCONHECIDO = "Inscrito Desconhecido"      # idem — inscrito sem cupom (ou cupom não mapeado); reaproveita valor já existente no portal
ORIGEM_VALOR_CUPOM_DESCONTO = "Cupom de Desconto"                 # idem — inscrito com cupom de um assessor mapeado
ORIGEM_VALOR_TRAFEGO_PAGO = "Trafego Pago"                        # idem — cupom de canal (não de assessor), ex: "MILETO"
VALOR_PRESENTE = "Presente"             # idem
VALOR_NAO_PRESENTE = "Não Presente"     # idem


# ---------------------------------------------------------------------------
# Bitrix24
# ---------------------------------------------------------------------------
def bitrix_call(method: str, payload: dict) -> dict:
    url = f"{BITRIX_WEBHOOK_URL}/{method}"
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"Bitrix24 error em {method}: {body}")
    return body["result"]


def get_lead(lead_id) -> dict:
    return bitrix_call("crm.lead.get", {"id": lead_id})


def bitrix_list_all(method: str, payload: dict) -> list:
    """Como bitrix_call, mas pagina automaticamente usando o campo "next"
    da resposta até esgotar os resultados (crm.*.list limita a 50 por
    página por padrão)."""
    results = []
    start = 0
    url = f"{BITRIX_WEBHOOK_URL}/{method}"
    while True:
        log.info("%s: buscando página (start=%s)...", method, start)
        resp = requests.post(url, json={**payload, "start": start}, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"Bitrix24 error em {method}: {body}")
        results.extend(body["result"])
        log.info("%s: %d registro(s) coletado(s) até agora.", method, len(results))
        if "next" not in body:
            break
        start = body["next"]
    return results


def _find_lead_ids_by_comm(comm_type: str, value: str) -> list[int]:
    result = bitrix_call(
        "crm.duplicate.findbycomm",
        {"entity_type": "LEAD", "type": comm_type, "values": [value]},
    )
    if isinstance(result, list):
        return result
    return result.get("LEAD", [])


def find_lead_ids_by_phone(phone: str) -> list[int]:
    return _find_lead_ids_by_comm("PHONE", phone)


def find_lead_ids_by_email(email: str) -> list[int]:
    return _find_lead_ids_by_comm("EMAIL", normalize_email(email))


_enum_id_cache: dict[tuple[str, str], str] = {}


def resolve_enum_id(field_code: str, value_text: str) -> str:
    """Descobre o ID numérico de um item de lista (campo tipo enumeration)
    a partir do texto exibido na UI, e cacheia o resultado.

    Existe porque campos enumeration no Bitrix24 exigem o ID numérico do
    item nas chamadas de update/add — mandar o texto (ex: "Presente") é
    aceito sem erro pela API, mas o valor é silenciosamente ignorado.
    Resolver isso em runtime evita ter que hardcodar e recolar esses IDs
    toda vez que o portal muda (já nos mordeu uma vez).
    """
    cache_key = (field_code, value_text)
    if cache_key in _enum_id_cache:
        return _enum_id_cache[cache_key]

    fields = bitrix_call("crm.lead.userfield.list", {"filter": {"FIELD_NAME": field_code}})
    for f in fields:
        for item in f.get("LIST", []):
            if item.get("VALUE") == value_text:
                _enum_id_cache[cache_key] = item["ID"]
                return item["ID"]

    raise ValueError(f"Item '{value_text}' não encontrado na lista do campo {field_code}")


_user_id_cache: dict[str, int] = {}


def resolve_user_id_by_email(email: str) -> int:
    """Descobre o ID numérico de um usuário do Bitrix a partir do e-mail
    (pra preencher ASSIGNED_BY_ID/"Pessoa Responsável"), e cacheia o
    resultado. Requer que o webhook de entrada tenha permissão de usuários,
    não só CRM."""
    if email in _user_id_cache:
        return _user_id_cache[email]

    users = bitrix_call("user.get", {"filter": {"EMAIL": email}})
    if not users:
        raise ValueError(f"Nenhum usuário Bitrix encontrado com e-mail {email}")

    user_id = int(users[0]["ID"])
    _user_id_cache[email] = user_id
    return user_id


# ---------------------------------------------------------------------------
# Sympla
# ---------------------------------------------------------------------------
def get_all_events() -> list[dict]:
    """Lista todos os eventos do organizador, paginando até acabar."""
    events = []
    page = 1
    headers = {"s_token": SYMPLA_TOKEN}
    while True:
        resp = requests.get(f"{SYMPLA_BASE}/events", headers=headers, params={"page": page}, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            break
        events.extend(data)
        page += 1
        sleep(0.3)
    return events


def list_upcoming_events(days_back: int = 1) -> list[dict]:
    """Filtra get_all_events() pros eventos que ainda vão acontecer (mais
    uma margem de alguns dias pra trás, pra cobrir diferença de fuso e
    eventos em andamento). Eventos antigos não interessam pra Automação A:
    ela só avança Leads que ainda não passaram pela etapa, e isso só
    acontece antes do evento rolar.

    days_back controla a margem: 1 dia é suficiente pra fuso horário, mas
    pode aumentar se algum evento válido ficar de fora por engano."""
    from datetime import date, timedelta

    cutoff = (date.today() - timedelta(days=days_back)).isoformat()
    events = get_all_events()
    return [e for e in events if (e.get("start_date") or "")[:10] >= cutoff]


def resolve_event_id(reference_id: str) -> str:
    """Converte o ID numérico (o que aparece no painel do organizador,
    ex: painel-do-evento?id=3463470) para o id alfanumérico interno que
    a API usa nos endpoints de participantes (ex: 's2e7f41')."""
    reference_id = str(reference_id)
    for event in get_all_events():
        if str(event.get("reference_id")) == reference_id:
            return event["id"]
    raise ValueError(f"Nenhum evento encontrado com reference_id={reference_id}")


def get_sympla_all_participants(event_id: str) -> list[dict]:
    """Retorna TODOS os participantes inscritos no evento, com ou sem
    check-in feito."""
    participants = []
    page = 1
    headers = {"s_token": SYMPLA_TOKEN}
    while True:
        url = f"{SYMPLA_BASE}/events/{event_id}/participants"
        resp = requests.get(url, headers=headers, params={"page": page}, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            break
        participants.extend(data)
        page += 1
        sleep(0.3)
    return participants


def get_sympla_all_orders(event_id: str) -> list[dict]:
    """Retorna TODOS os pedidos (orders) do evento, paginando — mesmo
    padrão de get_sympla_all_participants. Cada pedido pode trazer um
    cupom de desconto (discount_code) usado na inscrição."""
    orders = []
    page = 1
    headers = {"s_token": SYMPLA_TOKEN}
    while True:
        url = f"{SYMPLA_BASE}/events/{event_id}/orders"
        resp = requests.get(url, headers=headers, params={"page": page}, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            break
        orders.extend(data)
        page += 1
        sleep(0.3)
    return orders


def _is_no_discount_value(value: str) -> bool:
    """A Sympla usa a string "0" (às vezes "0.00") pra indicar que o
    pedido NÃO teve desconto — não é vazia/None, então "value or ''" não
    pega esse caso: precisa checar o conteúdo."""
    return value.strip().strip("0.") == ""


def build_cupom_by_order_id(orders: list[dict]) -> dict[str, str]:
    result = {}
    for order in orders:
        if order.get("id") is None:
            continue
        value = str(order.get("discount_code") or "").strip()
        result[str(order["id"])] = "" if _is_no_discount_value(value) else value
    return result


def normalize_cupom(raw: str) -> str:
    return (raw or "").strip().upper()


def extract_discount_code(participant: dict, get_cupom_by_order_id) -> str:
    """Resolve o cupom usado por um participante: primeiro tenta o campo
    direto "order_discount" do participante, senão cai pro mapa
    order_id -> discount_code (construído a partir de /orders).
    get_cupom_by_order_id é um callable preguiçoso — só busca /orders se
    o campo direto vier vazio e houver mesmo um order_id pra consultar."""
    direct = str(participant.get("order_discount") or "").strip()
    if direct and not _is_no_discount_value(direct):
        return direct
    order_id = participant.get("order_id")
    if order_id is None:
        return ""
    return (get_cupom_by_order_id().get(str(order_id)) or "").strip()


def extract_phone(participant: dict) -> str:
    """O telefone vem como resposta dentro de custom_form, atrelada à
    pergunta do formulário de inscrição (o texto pode variar entre
    eventos: "WhatsApp/Telefone", "Celular", "Telefone para contato" etc).
    A Sympla usa as chaves "name" (pergunta) e "value" (resposta)."""
    for field in participant.get("custom_form") or []:
        question = (field.get("name") or "").lower()
        if any(kw in question for kw in ("telefone", "whatsapp", "celular")):
            return field.get("value", "")
    return ""


def format_phone_br(raw: str) -> str:
    """Formata um telefone bruto pro padrão +55DDDNUMERO, o mesmo formato
    que o Bitrix24 usa quando alguém preenche manualmente."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if not digits.startswith("55"):
        digits = "55" + digits
    return f"+{digits}"


# ---------------------------------------------------------------------------
# Normalização / matching por nome e e-mail
# ---------------------------------------------------------------------------
def normalize_name(raw: str) -> str:
    """Lowercase, remove acentos e colapsa espaços — pra comparar nomes
    ignorando maiúsculas/formatação entre Sympla e Bitrix24."""
    text = (raw or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_email(raw: str) -> str:
    """Lowercase + strip, pra comparar e-mail ignorando maiúsculas/espaços
    (ex: " Joao@Empresa.COM " e "joao@empresa.com" devem bater)."""
    return (raw or "").strip().lower()


def participant_full_name(participant: dict) -> str:
    return f"{participant.get('first_name', '').strip()} {participant.get('last_name', '').strip()}".strip()
