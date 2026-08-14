"""
Funções puras de normalização/extração de dados — zero chamada de rede.
Usadas pelo motor de sincronização (matching, criação de lead) e
testáveis isoladamente sem precisar de nenhuma credencial.
"""

import logging
import re
import unicodedata

log = logging.getLogger("common.normalization")


def format_phone_br(raw: str) -> str:
    """Formata um telefone bruto pro padrão +55DDDNUMERO, o mesmo formato
    que o Bitrix24 usa quando alguém preenche manualmente."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if not digits.startswith("55"):
        digits = "55" + digits
    return f"+{digits}"


def normalize_phone_suffix(raw: str) -> str:
    """Chave de COMPARAÇÃO pra achar duplicados por telefone — não é o
    formato canônico gravado no Bitrix (isso continua sendo
    format_phone_br). Remove tudo que não é dígito, remove o DDI 55 se
    presente, e remove o 9º dígito de celular se for o caso — assim
    "(85) 98863-2263" e "8863-2263" (mesmo número, um com o 9 e outro
    sem, os dois formatos coexistem em cadastros antigos) convergem pra
    MESMA chave em vez de parecerem números diferentes."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if len(digits) > 11 and digits.startswith("55"):
        digits = digits[2:]
    if len(digits) == 11 and digits[2] == "9":
        digits = digits[:2] + digits[3:]
    return digits


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


def extract_cpf(participant: dict) -> str:
    """Mesmo padrão de extract_phone: CPF vem como resposta dentro de
    custom_form (a pergunta varia entre eventos: "CPF", "Qual seu CPF?"
    etc) — só alguns eventos pedem CPF no formulário de inscrição."""
    for field in participant.get("custom_form") or []:
        question = (field.get("name") or "").lower()
        if "cpf" in question:
            return field.get("value", "")
    return ""


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


def normalize_cupom(raw: str) -> str:
    return (raw or "").strip().upper()


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


def format_event_label(event_name: str, event_date: str) -> str:
    """Formata o label do item na lista do campo Filtrar Evento:
    "DD/MM/AA - Nome do Evento". event_date no formato YYYY-MM-DD (o que já
    circula no código, resultado de (event.get("start_date") or "")[:10]).

    Função pura — usada tanto na pré-população em massa
    (setup_custom_fields.py, todos os eventos de get_all_events()) quanto
    incremental em runtime (automacao_a_inscricoes.py, evento por evento),
    pra garantir texto IDÊNTICO nos dois lugares: qualquer divergência de
    formatação cria um item duplicado na lista do Bitrix pro mesmo evento
    (ex: "04/03/26" vs "04/03/2026" viram duas entradas diferentes).
    """
    if event_date and len(event_date) == 10 and event_date[4] == "-" and event_date[7] == "-":
        yyyy, mm, dd = event_date.split("-")
        date_part = f"{dd}/{mm}/{yyyy[2:]}"
    else:
        date_part = "??/??/??"
        log.warning("event_date inesperado ('%s') formatando label do evento '%s' — usando placeholder.", event_date, event_name)
    return f"{date_part} - {event_name}".strip()
