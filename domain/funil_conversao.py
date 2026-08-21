"""
Funil de conversão de um evento: quantos inscritos (via Lead vinculado ao
item da SPA "Eventos Sympla") chegaram até cada degrau do funil novo —
Inscrito Pro Evento -> Pós Evento -> Reunião -> Convertido (Negócio).

Função pura: recebe os Leads já buscados (dict com ID/STATUS_ID), decide só
a classificação — quem busca os Leads de verdade é interface/routes_eventos.py
via common.find_leads_by_evento_item.

O Bitrix só guarda o estágio ATUAL de cada Lead, não histórico — a
contagem é cumulativa ("chegou até aqui ou foi além"), assumindo que a
ordem dos estágios do funil novo é sequencial (SORT crescente no Bitrix,
confirmado ao vivo via crm.status.list: NEWLEAD < NEWFUP < Inscrito <
Pós Evento < Reunião < Espólio < Convertido). JUNK (perdido) e qualquer
estágio de OLD_FUNNEL_STAGES (Lead vinculado ao evento mas nunca
promovido pro funil novo — ver services/lead_sync_service.py) não têm
posição clara nessa ordem — viram buckets à parte, não entram nos 4
degraus principais nem inflam a contagem deles.
"""

from common import OLD_FUNNEL_STAGES

BUCKETS_ORDENADOS = ["inscrito", "pos_evento", "reuniao", "convertido"]


def classificar_lead(status_id: str | None, stage_inscrito: str, stage_pos_evento: str, stage_reuniao: str) -> str:
    """Retorna um dos buckets: inscrito|pos_evento|reuniao|convertido|
    perdido|fora_do_funil. A posição do estágio numa lista ordenada
    (NEWLEAD, NEWFUP, stage_inscrito, stage_pos_evento, stage_reuniao,
    NEWESPOLIO, CONVERTED) decide até onde o Lead chegou."""
    if status_id == "JUNK":
        return "perdido"
    if status_id in OLD_FUNNEL_STAGES:
        return "fora_do_funil"

    ordem = ["NEWLEAD", "NEWFUP", stage_inscrito, stage_pos_evento, stage_reuniao, "NEWESPOLIO", "CONVERTED"]
    if status_id not in ordem:
        return "fora_do_funil"

    indice = ordem.index(status_id)
    if indice >= ordem.index("CONVERTED"):
        return "convertido"
    if indice >= ordem.index(stage_reuniao):
        return "reuniao"
    if indice >= ordem.index(stage_pos_evento):
        return "pos_evento"
    if indice >= ordem.index(stage_inscrito):
        return "inscrito"
    return "fora_do_funil"  # NEWLEAD/NEWFUP vinculado ao evento — caso raro, ainda "cru"


def resumo_funil(leads: list[dict], stage_inscrito: str, stage_pos_evento: str, stage_reuniao: str) -> dict:
    """Conta CUMULATIVO por bucket: quem chegou em "reuniao" também soma
    em "inscrito" e "pos_evento". "perdido" e "fora_do_funil" ficam de
    fora dessa soma cumulativa — não fazem sentido somados aos degraus,
    são expostos à parte como referência. "total" é a contagem bruta de
    Leads vinculados ao evento, todos os buckets somados."""
    contagem = {"inscrito": 0, "pos_evento": 0, "reuniao": 0, "convertido": 0, "perdido": 0, "fora_do_funil": 0}

    for lead in leads:
        bucket = classificar_lead(lead.get("STATUS_ID"), stage_inscrito, stage_pos_evento, stage_reuniao)
        if bucket in ("perdido", "fora_do_funil"):
            contagem[bucket] += 1
            continue
        indice_alcancado = BUCKETS_ORDENADOS.index(bucket)
        for i in range(indice_alcancado + 1):
            contagem[BUCKETS_ORDENADOS[i]] += 1

    contagem["total"] = len(leads)
    return contagem
