"""
Chamadas à API do Bitrix24. Camada de I/O pura — não decide nada de
negócio, só sabe conversar com o portal (incluindo retry em falha
transitória, via common._retry).
"""

import logging

from ._retry import request_with_retry
from .constants import BITRIX_WEBHOOK_URL
from .normalization import normalize_email

log = logging.getLogger("common.bitrix_client")


def bitrix_call(method: str, payload: dict) -> dict:
    url = f"{BITRIX_WEBHOOK_URL}/{method}"
    resp = request_with_retry("POST", url, json=payload, timeout=30)
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
        resp = request_with_retry("POST", url, json={**payload, "start": start}, timeout=30)
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


def _merge_enum_items(current_items: list[dict], new_values: list[str]) -> tuple[list[dict], list[str]]:
    """crm.lead.userfield.update substitui a LIST inteira — reenviar os
    itens atuais (com ID, pra preservar) + os novos (sem ID, pra criar) é
    o jeito de adicionar sem apagar nada. Retorna (lista pronta pro update,
    valores que eram novos).

    SORT dos itens existentes é preservado como está (não mexe em quem já
    tinha sido ordenado manualmente na tela do Bitrix); itens novos entram
    incrementando a partir do maior SORT atual, na ordem em que aparecem em
    new_values — sem isso, todo item nasce com o mesmo SORT default (500),
    e o Bitrix não garante ordem estável de exibição entre itens empatados."""
    current_values = {item.get("VALUE") for item in current_items}
    faltando = [v for v in new_values if v not in current_values]
    merged = [{"ID": item["ID"], "VALUE": item["VALUE"], "SORT": item.get("SORT", 500)} for item in current_items]
    next_sort = max((int(item.get("SORT", 500)) for item in current_items), default=0) + 10
    for v in faltando:
        merged.append({"VALUE": v, "SORT": next_sort})
        next_sort += 10
    return merged, faltando


def ensure_enum_value(field_code: str, value_text: str) -> str:
    """Como resolve_enum_id, mas ADICIONA o item na lista do campo se ele
    ainda não existir, em vez de levantar erro — pensado pra listas que
    crescem em runtime (Filtrar Evento: um item novo por evento criado na
    Sympla). resolve_enum_id continua servindo listas fixas (Origem,
    Presente no evento), onde um item faltando é sinal de bug/config
    errada, não algo pra criar sozinho.

    Cacheia no mesmo _enum_id_cache que resolve_enum_id usa, então dentro
    de um run só bate na API uma vez por (campo, valor). Não cria o CAMPO
    em si (isso é responsabilidade de setup_custom_fields.py) — só
    adiciona itens à LIST de um campo que já existe.
    """
    cache_key = (field_code, value_text)
    if cache_key in _enum_id_cache:
        return _enum_id_cache[cache_key]

    fields = bitrix_call("crm.lead.userfield.list", {"filter": {"FIELD_NAME": field_code}})
    if not fields:
        raise ValueError(f"Campo {field_code} não existe — rode setup_custom_fields.py antes.")
    field = fields[0]
    current_items = field.get("LIST", [])
    for item in current_items:
        if item.get("VALUE") == value_text:
            _enum_id_cache[cache_key] = item["ID"]
            return item["ID"]

    updated_list, _ = _merge_enum_items(current_items, [value_text])
    bitrix_call("crm.lead.userfield.update", {"id": field["ID"], "fields": {"LIST": updated_list}})

    # userfield.update não devolve o ID do item recém-criado — relê pra
    # descobrir. Se dois runs concorrentes criaram o mesmo item ao mesmo
    # tempo (o bloco concurrency do workflow deveria evitar isso, mas por
    # segurança), converge pro de menor ID, pra todo mundo concordar no
    # mesmo ID daqui pra frente mesmo com um duplicado órfão pendurado.
    refreshed = bitrix_call("crm.lead.userfield.list", {"filter": {"FIELD_NAME": field_code}})
    matches = [item for item in refreshed[0].get("LIST", []) if item.get("VALUE") == value_text]
    if not matches:
        raise RuntimeError(f"Item '{value_text}' não apareceu na lista do campo {field_code} depois de tentar criar.")
    if len(matches) > 1:
        log.warning(
            "Campo %s: %d itens com o mesmo texto '%s' (IDs %s) — provável corrida entre dois runs. "
            "Usando o de menor ID; considere apagar o(s) duplicado(s) manualmente na tela de Campos Personalizados.",
            field_code, len(matches), value_text, [m["ID"] for m in matches],
        )
    item = min(matches, key=lambda m: int(m["ID"]))
    _enum_id_cache[cache_key] = item["ID"]
    log.info("Item '%s' criado na lista do campo %s (ID %s).", value_text, field_code, item["ID"])
    return item["ID"]


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
