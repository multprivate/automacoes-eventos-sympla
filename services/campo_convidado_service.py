"""
Mantém as OPÇÕES do campo de Lead "Cliente convidado para:"
(FIELD_CLIENTE_CONVIDADO_PARA) sempre com todos os eventos já cadastrados
na Sympla, ordenadas da data mais recente pra mais antiga.

Diferente de FIELD_FILTRAR_EVENTO (common.ensure_enum_value), que só
cresce em runtime (um item por evento, na ordem em que é usado pela
primeira vez, nunca reordenado — ver common/bitrix_client.py::
_merge_enum_items), este campo precisa refletir a ordem cronológica
inteira toda vez que roda, porque a regra de negócio é "mais recente
primeiro", não "na ordem em que apareceu". Por isso mora numa rotina
separada (services/campo_convidado_service.py + sincronizar_lista_
convidados.py, rodando 1x/dia via GitHub Actions) em vez de dentro do
ciclo de 30 min da Automação A: não preenche nada em nenhum Lead, não
reage a inscrição nova de ninguém — só a lista de opções do campo, uma
tarefa de baixíssima urgência que não vale o risco/custo de rodar (e
escrever no Bitrix) a cada tick do motor principal.
"""

import logging

from common import (
    FIELD_CLIENTE_CONVIDADO_PARA,
    bitrix_call,
    format_event_label,
    get_all_events,
    merge_enum_items_sorted,
)

log = logging.getLogger("services.campo_convidado_service")


def sincronizar_opcoes_evento() -> dict:
    """Busca todos os eventos da Sympla, monta os labels no mesmo formato
    de FIELD_FILTRAR_EVENTO ("DD/MM/AA - Nome do Evento"), ordena da data
    mais recente pra mais antiga, e atualiza a LIST do campo só se algo
    realmente mudou (evento novo, ou ordem desatualizada)."""
    eventos = sorted(get_all_events(), key=lambda e: (e.get("start_date") or ""), reverse=True)
    labels = [format_event_label(e.get("name", ""), (e.get("start_date") or "")[:10]) for e in eventos]

    fields = bitrix_call("crm.lead.userfield.list", {"filter": {"FIELD_NAME": FIELD_CLIENTE_CONVIDADO_PARA}})
    if not fields:
        raise ValueError(f"Campo {FIELD_CLIENTE_CONVIDADO_PARA} não existe no Bitrix.")
    field = fields[0]
    current_items = field.get("LIST", [])

    updated_list = merge_enum_items_sorted(current_items, labels)

    def _chave_comparacao(items: list[dict]) -> list[tuple]:
        return [(item.get("VALUE"), item.get("ID")) for item in items]

    if _chave_comparacao(updated_list) == _chave_comparacao(current_items):
        log.info("Campo %s já está com os %d evento(s) na ordem certa — nada a fazer.", FIELD_CLIENTE_CONVIDADO_PARA, len(labels))
        return {"total_eventos": len(labels), "atualizado": False}

    bitrix_call("crm.lead.userfield.update", {"id": field["ID"], "fields": {"LIST": updated_list}})
    log.info("Campo %s atualizado com %d evento(s), ordenados da data mais recente pra mais antiga.", FIELD_CLIENTE_CONVIDADO_PARA, len(labels))
    return {"total_eventos": len(labels), "atualizado": True}
