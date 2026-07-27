"""
Automação A: a cada execução, descobre sozinha quais eventos estão
próximos de acontecer na Sympla (list_upcoming_events — não depende mais
de uma lista fixa de IDs) e casa cada inscrito com um Lead do Bitrix24 por
telefone, e-mail ou, se não achar, por nome (ignorando
maiúsculas/acentos/espaçamento). Quando acha, avança o Lead pra "Inscrito
Pro Evento" e preenche Data do evento + Nome do evento + o ID interno do
evento Sympla. Quando não acha, cria um Lead novo.

Só chama a API do Bitrix quando há inscrito NOVO desde a última execução
— um cache local (.cache/sympla_processed.json, persistido entre runs do
GitHub Actions via actions/cache) guarda quem já foi processado por
evento, então rodar sem nenhuma inscrição nova não gera nenhuma chamada
ao Bitrix.

É idempotente: só escreve os campos que realmente mudaram, então pode
rodar quantas vezes quiser (pensada pra rodar a cada 7 minutos via
GitHub Actions — veja .github/workflows/automacao_a.yml).

Uso:
    python automacao_a_inscricoes.py
"""

import json
import logging
import os

from common import (
    bitrix_call,
    bitrix_list_all,
    build_cupom_by_order_id,
    extract_discount_code,
    find_lead_ids_by_email,
    find_lead_ids_by_phone,
    format_phone_br,
    extract_phone,
    get_lead,
    get_sympla_all_orders,
    get_sympla_all_participants,
    list_upcoming_events,
    normalize_cupom,
    normalize_email,
    normalize_name,
    participant_full_name,
    resolve_enum_id,
    resolve_user_id_by_email,
    FIELD_DATA_DO_EVENTO,
    FIELD_NOME_DO_EVENTO,
    FIELD_SYMPLA_EVENT_ID,
    FIELD_ORIGEM,
    ORIGEM_VALOR_CUPOM_DESCONTO,
    ORIGEM_VALOR_INSCRITO_DESCONHECIDO,
    ORIGEM_VALOR_TRAFEGO_PAGO,
    OLD_FUNNEL_STAGES,
    STAGE_INSCRITO_PRO_EVENTO,
    STAGES_SAFE_TO_ADVANCE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("automacao_a_inscricoes")

CACHE_PATH = ".cache/sympla_processed.json"


# ---------------------------------------------------------------------------
# Cache de inscritos já processados (evita chamar o Bitrix sem necessidade)
# ---------------------------------------------------------------------------
def load_processed_cache() -> dict[str, set[str]]:
    if not os.path.exists(CACHE_PATH):
        return {}
    with open(CACHE_PATH) as f:
        raw = json.load(f)
    return {event_id: set(ids) for event_id, ids in raw.items()}


def save_processed_cache(cache: dict[str, set[str]]) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    raw = {event_id: sorted(ids) for event_id, ids in cache.items()}
    with open(CACHE_PATH, "w") as f:
        json.dump(raw, f)


# ---------------------------------------------------------------------------
# Fallback por nome: busca só os Leads cujo NAME contém o nome do inscrito
# (filtro "%NAME" do Bitrix) em vez de baixar o portal inteiro — o portal
# tem milhares de Leads, então indexar tudo em memória a cada fallback
# seria caro demais. A comparação final ainda é feita localmente com
# normalize_name (ignora acento/maiúscula/espaçamento), o filtro do Bitrix
# só reduz a lista de candidatos.
# ---------------------------------------------------------------------------
def find_lead_ids_by_name(full_name: str) -> list[int]:
    key = normalize_name(full_name)
    if not key:
        return []
    candidates = bitrix_list_all(
        "crm.lead.list",
        {"filter": {"%NAME": full_name}, "select": ["ID", "NAME"]},
    )
    return [int(lead["ID"]) for lead in candidates if normalize_name(lead.get("NAME", "")) == key]


# ---------------------------------------------------------------------------
# Matching em cascata: telefone -> e-mail -> nome
# (próximo degrau natural, quando a Sympla passar a coletar CPF: checar CPF
# antes de telefone, é o identificador mais confiável)
# ---------------------------------------------------------------------------
def find_matching_lead_ids(phone_key: str, email: str, full_name: str) -> tuple[list[int], str | None]:
    if phone_key:
        lead_ids = find_lead_ids_by_phone(phone_key)
        if lead_ids:
            return lead_ids, "telefone"

    if email:
        lead_ids = find_lead_ids_by_email(email)
        if lead_ids:
            return lead_ids, "email"

    lead_ids = find_lead_ids_by_name(full_name)
    return lead_ids, ("nome" if lead_ids else None)


# ---------------------------------------------------------------------------
# Cupom -> assessor responsável (só usado na CRIAÇÃO de Lead novo — nunca
# sobrescreve responsável/origem de um Lead já existente que a automação
# encontrar por telefone/e-mail/nome).
#
# Espelha a aba "Mapa_Assessores" do Extrator.gs (Google Apps Script) já
# validada em produção — chave já normalizada (trim+upper). Atualizar aqui
# (e lá) quando entrar assessor novo ou uma variação de % do cupom (ex:
# "70% - IARA" além de "100.00% - IARA").
# ---------------------------------------------------------------------------
ASSESSOR_POR_CUPOM = {
    "100.00% - BRUNA": "bruna.tassia@multprivate.seg.br",
    "100.00% - EDUARDO": "eduardo.forte@multprivate.seg.br",
    "100.00% - IARA": "iara.araujo@multprivate.seg.br",
    "100.00% - JULIANA": "juliana.cintra@multprivate.com.br",
    "100.00% - MARCOS": "marcos.mourao@multprivate.com.br",
    "100.00% - RICARDO": "joao.nogueira@multprivate.seg.br",
    "100.00% - RODRIGO": "rodrigo.onias@multprivate.seg.br",
    "100.00% - STEFANO": "stefano.silva@multprivate.com.br",
    "100.00% - STHEFANY": "sthefany.muniz@multprivate.com.br",
    "100.00% - MUNIZ": "sthefany.muniz@multprivate.com.br",
    "100.00% - RAQUEL": "celedonio@multprivate.seg.br",
    "100.00% - THAIS": "thais.oliveira@multprivate.com.br",
    "100% - JOAO": "joao.nogueira@multprivate.seg.br",
}

# Cupons que não são de um assessor específico, e sim de um canal de
# aquisição — só marcam a Origem do Lead pra rastreio, sem responsável.
ORIGEM_POR_CUPOM_CANAL = {
    "100.00% - MILETO": ORIGEM_VALOR_TRAFEGO_PAGO,
}


def resolve_assessor_and_origem(cupom: str) -> tuple[str | None, str]:
    if not cupom:
        return None, ORIGEM_VALOR_INSCRITO_DESCONHECIDO

    key = normalize_cupom(cupom)

    email = ASSESSOR_POR_CUPOM.get(key)
    if email:
        return email, ORIGEM_VALOR_CUPOM_DESCONTO

    origem_canal = ORIGEM_POR_CUPOM_CANAL.get(key)
    if origem_canal:
        return None, origem_canal

    log.warning("Cupom '%s' não mapeado em ASSESSOR_POR_CUPOM nem ORIGEM_POR_CUPOM_CANAL — Lead fica sem responsável específico.", cupom)
    return None, ORIGEM_VALOR_INSCRITO_DESCONHECIDO


def build_cupom_map_loader(event_id: str):
    """Closure memoizado: só busca /orders da Sympla se algum participante
    novo realmente precisar (nenhum campo direto de cupom disponível)."""
    cache: dict[str, dict[str, str]] = {}

    def get() -> dict[str, str]:
        if "map" not in cache:
            cache["map"] = build_cupom_by_order_id(get_sympla_all_orders(event_id))
        return cache["map"]

    return get


def build_fields_to_advance(lead: dict, event_name: str, event_date: str, sympla_event_id: str) -> dict:
    """Monta só os campos que precisam mudar nesse Lead (idempotência)."""
    fields = {}
    status = lead.get("STATUS_ID")
    if status in STAGES_SAFE_TO_ADVANCE:
        fields["STATUS_ID"] = STAGE_INSCRITO_PRO_EVENTO
    elif status != STAGE_INSCRITO_PRO_EVENTO:
        log.info("Lead %s já está em estágio avançado (%s), não mexendo no estágio.", lead.get("ID"), status)

    if FIELD_DATA_DO_EVENTO and lead.get(FIELD_DATA_DO_EVENTO) != event_date:
        fields[FIELD_DATA_DO_EVENTO] = event_date
    if FIELD_NOME_DO_EVENTO and lead.get(FIELD_NOME_DO_EVENTO) != event_name:
        fields[FIELD_NOME_DO_EVENTO] = event_name
    if FIELD_SYMPLA_EVENT_ID and lead.get(FIELD_SYMPLA_EVENT_ID) != sympla_event_id:
        fields[FIELD_SYMPLA_EVENT_ID] = sympla_event_id
    return fields


def create_lead_from_participant(participant: dict, phone_raw: str, email: str, event_name: str, event_date: str, sympla_event_id: str, get_cupom_map) -> None:
    name = participant_full_name(participant)
    cupom = extract_discount_code(participant, get_cupom_map)
    assessor_email, origem_valor = resolve_assessor_and_origem(cupom)

    fields = {
        "NAME": name or "Inscrito Sympla",
        "TITLE": name or "Inscrito Sympla",
        "PHONE": [{"VALUE": format_phone_br(phone_raw), "VALUE_TYPE": "WORK"}],
        "STATUS_ID": STAGE_INSCRITO_PRO_EVENTO,
    }
    if FIELD_DATA_DO_EVENTO:
        fields[FIELD_DATA_DO_EVENTO] = event_date
    if FIELD_NOME_DO_EVENTO:
        fields[FIELD_NOME_DO_EVENTO] = event_name
    if FIELD_SYMPLA_EVENT_ID:
        fields[FIELD_SYMPLA_EVENT_ID] = sympla_event_id
    if FIELD_ORIGEM:
        fields[FIELD_ORIGEM] = resolve_enum_id(FIELD_ORIGEM, origem_valor)
    if assessor_email:
        fields["ASSIGNED_BY_ID"] = resolve_user_id_by_email(assessor_email)
    if email:
        fields["EMAIL"] = [{"VALUE": normalize_email(email), "VALUE_TYPE": "WORK"}]

    new_id = bitrix_call("crm.lead.add", {"fields": fields})
    responsavel_info = f", responsável={assessor_email}" if assessor_email else ""
    log.info("Novo lead %s criado pro participante %s (%s) — origem=%s%s.", new_id, participant.get("id"), name, origem_valor, responsavel_info)


def process_participant(participant: dict, event_name: str, event_date: str, event_id: str, get_cupom_map) -> bool:
    """Retorna True se o inscrito foi tratado com sucesso (atualizado, criado,
    ou legitimamente pulado — funil antigo/sem telefone), False se algo deu
    errado e precisa ser tentado de novo na próxima execução. Só entra no
    cache de "já processado" quem retorna True — assim uma falha transitória
    (permissão, campo faltando, rede) nunca faz a gente perder o inscrito
    pra sempre."""
    phone_raw = extract_phone(participant)
    phone_key = format_phone_br(phone_raw)
    email = participant.get("email") or ""
    full_name = participant_full_name(participant)

    try:
        lead_ids, match_method = find_matching_lead_ids(phone_key, email, full_name)
    except Exception as exc:
        log.error("Falha ao buscar lead pro inscrito %s: %s", participant.get("id"), exc)
        return False

    try:
        if lead_ids:
            for lead_id in lead_ids:
                lead = get_lead(lead_id)
                is_old_funnel = lead.get("STATUS_ID") in OLD_FUNNEL_STAGES
                fields = build_fields_to_advance(lead, event_name, event_date, event_id)
                if is_old_funnel:
                    # Defesa explícita: funil antigo pode ganhar os campos
                    # do evento (visibilidade de que se inscreveu de novo),
                    # mas o estágio nunca muda — mesmo que build_fields_to_advance
                    # mude de regra no futuro.
                    fields.pop("STATUS_ID", None)
                if fields:
                    bitrix_call("crm.lead.update", {"id": lead_id, "fields": fields})
                    tag = " (funil antigo, só campos de evento)" if is_old_funnel else ""
                    log.info("Lead %s atualizado (match por %s)%s: %s", lead_id, match_method, tag, fields)
                else:
                    log.info("Lead %s já estava em dia, nada pra atualizar.", lead_id)
        elif phone_key:
            create_lead_from_participant(participant, phone_raw, email, event_name, event_date, event_id, get_cupom_map)
        else:
            log.warning("Inscrito sem telefone e sem nome/e-mail batendo com Lead existente, pulando: %s", participant.get("id"))
        return True
    except Exception as exc:
        log.error("Falha ao processar inscrito %s: %s", participant.get("id"), exc)
        return False


def process_event(event: dict, cache: dict[str, set[str]]) -> bool:
    """Retorna True se o cache desse evento mudou (pra saber se precisa salvar)."""
    event_id = event["id"]
    event_name = event.get("name", "")
    event_date = (event.get("start_date") or "")[:10]  # YYYY-MM-DD

    participants = get_sympla_all_participants(event_id)
    seen_ids = cache.get(event_id, set())
    new_participants = [p for p in participants if str(p.get("id")) not in seen_ids]

    if not new_participants:
        log.info("Nenhum inscrito novo em %s (id interno %s) — %d inscrito(s) já processado(s) antes.", event_name, event_id, len(participants))
        return False

    log.info("%d inscrito(s) novo(s) em %s (id interno %s) de %d no total.", len(new_participants), event_name, event_id, len(participants))
    get_cupom_map = build_cupom_map_loader(event_id)
    newly_done = {
        str(participant.get("id"))
        for participant in new_participants
        if process_participant(participant, event_name, event_date, event_id, get_cupom_map)
    }

    if not newly_done:
        return False
    cache[event_id] = seen_ids | newly_done
    return True


def main() -> None:
    test_event_ids = {e.strip() for e in os.environ.get("TEST_EVENT_IDS", "").split(",") if e.strip()}

    cache = load_processed_cache()
    events = list_upcoming_events()
    log.info("%d evento(s) próximo(s) encontrado(s) na Sympla.", len(events))

    if test_event_ids:
        events = [e for e in events if e["id"] in test_event_ids]
        log.info("Modo teste ativo (TEST_EVENT_IDS) — restrito a %d evento(s): %s", len(events), sorted(test_event_ids))

    cache_changed = False
    for event in events:
        if process_event(event, cache):
            cache_changed = True

    if cache_changed:
        save_processed_cache(cache)


if __name__ == "__main__":
    main()
