"""
Chamadas à API de itens dinâmicos (Smart Process / SPA) do Bitrix24 —
usado pra ler/criar/atualizar itens da SPA nativa "Eventos Sympla"
(entityTypeId 1112, ver common/constants.py). Camada de I/O pura, mesmo
espírito de bitrix_client.py — sem decisão de negócio aqui.

`crm.item.*` tem um formato de resposta diferente das entidades clássicas
(Lead/Contact): o resultado vem embrulhado em {"item": {...}} ou
{"items": [...]}, em vez do array/objeto direto que crm.lead.* devolve.
"""

from .bitrix_client import bitrix_call
from .constants import BITRIX_SPA_ENTITY_TYPE_ID, FIELD_SPA_SYMPLA_EVENT_ID


def find_item_by_sympla_event_id(sympla_event_id: str, entity_type_id: int = BITRIX_SPA_ENTITY_TYPE_ID, field_sympla_event_id: str = FIELD_SPA_SYMPLA_EVENT_ID) -> dict | None:
    result = bitrix_call(
        "crm.item.list",
        {
            "entityTypeId": entity_type_id,
            "filter": {field_sympla_event_id: sympla_event_id},
            "select": ["id", "title", field_sympla_event_id],
        },
    )
    items = result.get("items", [])
    return items[0] if items else None


def add_item(fields: dict, entity_type_id: int = BITRIX_SPA_ENTITY_TYPE_ID) -> int:
    result = bitrix_call("crm.item.add", {"entityTypeId": entity_type_id, "fields": fields})
    return int(result["item"]["id"])


def update_item(item_id: int, fields: dict, entity_type_id: int = BITRIX_SPA_ENTITY_TYPE_ID) -> None:
    bitrix_call("crm.item.update", {"entityTypeId": entity_type_id, "id": item_id, "fields": fields})


def get_item(item_id: int, entity_type_id: int = BITRIX_SPA_ENTITY_TYPE_ID) -> dict:
    result = bitrix_call("crm.item.get", {"entityTypeId": entity_type_id, "id": item_id})
    return result["item"]
