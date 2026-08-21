"""
Links clicáveis pros cards do Bitrix24 no painel. BITRIX_PORTAL_URL é a
base do portal derivada do webhook (ver common/constants.py) — nunca usada
em chamada de API, só pra montar href.
"""

from common.constants import BITRIX_PORTAL_URL


def lead_url(lead_id: int | str) -> str:
    return f"{BITRIX_PORTAL_URL}/crm/lead/details/{lead_id}/"


def contact_url(contact_id: int | str) -> str:
    """Mesma convenção do Lead, trocando o segmento da entidade — é o
    padrão do Bitrix24 pra qualquer entidade de CRM. Não confirmado em
    nenhuma chamada de API deste projeto (o portal nunca expôs um link de
    Contato antes desta feature) — na pior das hipóteses um id errado
    aqui é um 404 visível, não um risco de dado."""
    return f"{BITRIX_PORTAL_URL}/crm/contact/details/{contact_id}/"
