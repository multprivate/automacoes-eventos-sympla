"""
Chamadas à API da Sympla. Camada de I/O pura — mesmo espírito de
bitrix_client.py: sem decisão de negócio aqui, só transporte (com retry
via common._retry).
"""

from time import sleep

from ._retry import request_with_retry
from .constants import SYMPLA_BASE, SYMPLA_TOKEN


def get_all_events() -> list[dict]:
    """Lista todos os eventos do organizador, paginando até acabar."""
    events = []
    page = 1
    headers = {"s_token": SYMPLA_TOKEN}
    while True:
        resp = request_with_retry("GET", f"{SYMPLA_BASE}/events", headers=headers, params={"page": page}, timeout=30)
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
        resp = request_with_retry("GET", url, headers=headers, params={"page": page}, timeout=30)
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
        resp = request_with_retry("GET", url, headers=headers, params={"page": page}, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            break
        orders.extend(data)
        page += 1
        sleep(0.3)
    return orders
