"""
Roda uma vez só: garante que existem todos os campos customizados e o
estágio de Lead que as automações precisam, e imprime os códigos prontos
pra colar no .env. Idempotente: acha campos existentes pelo FIELD_NAME
exato (UF_CRM_<field_name>) — crm.lead.userfield.list não devolve o rótulo
(EDIT_FORM_LABEL) na resposta, então não dá pra buscar por texto visível;
o FIELD_NAME funciona porque os campos que este script cria sempre usam a
mesma convenção de nome.

Uso:
    python setup_custom_fields.py
"""

from common import (
    bitrix_call,
    format_event_label,
    get_all_events,
    ORIGEM_VALOR_CUPOM_DESCONTO,
    ORIGEM_VALOR_FORMULARIO,
    ORIGEM_VALOR_INSCRITO_DESCONHECIDO,
    ORIGEM_VALOR_TRAFEGO_PAGO,
    VALOR_PRESENTE,
    VALOR_NAO_PRESENTE,
    _merge_enum_items,
)


def _find_field_by_name(field_name: str) -> dict | None:
    existing = bitrix_call("crm.lead.userfield.list", {"filter": {"FIELD_NAME": f"UF_CRM_{field_name}"}})
    return existing[0] if existing else None


def create_string_field(field_name: str, label: str) -> str:
    existing = _find_field_by_name(field_name)
    if existing:
        code = existing["FIELD_NAME"]
        print(f"Campo '{label}' já existe: {code}")
        return code

    result = bitrix_call(
        "crm.lead.userfield.add",
        {
            "fields": {
                "FIELD_NAME": field_name,
                "USER_TYPE_ID": "string",
                "EDIT_FORM_LABEL": {"pt": label},
                "LIST_COLUMN_LABEL": {"pt": label},
                "LIST_FILTER_LABEL": {"pt": label},
            }
        },
    )
    field = bitrix_call("crm.lead.userfield.list", {"filter": {"ID": result}})
    code = field[0]["FIELD_NAME"]
    print(f"Campo '{label}' criado: {code}")
    return code


def create_enum_field(field_name: str, label: str, values: list[str]) -> str:
    existing = _find_field_by_name(field_name)
    if existing:
        code = existing["FIELD_NAME"]
        updated_list, faltando = _merge_enum_items(existing.get("LIST", []), values)
        if not faltando:
            print(f"Campo '{label}' já tem todos os valores necessários: {code}")
            return code

        bitrix_call("crm.lead.userfield.update", {"id": existing["ID"], "fields": {"LIST": updated_list}})
        print(f"Campo '{label}' ({code}) atualizado com os novos valores: {faltando}")
        return code

    result = bitrix_call(
        "crm.lead.userfield.add",
        {
            "fields": {
                "FIELD_NAME": field_name,
                "USER_TYPE_ID": "enumeration",
                "EDIT_FORM_LABEL": {"pt": label},
                "LIST_COLUMN_LABEL": {"pt": label},
                "LIST_FILTER_LABEL": {"pt": label},
                "LIST": [{"VALUE": v, "SORT": (i + 1) * 10} for i, v in enumerate(values)],
            }
        },
    )
    field = bitrix_call("crm.lead.userfield.list", {"filter": {"ID": result}})
    code = field[0]["FIELD_NAME"]
    print(f"Campo '{label}' criado: {code}")
    return code


def ensure_lead_stage(name_contains: str) -> str:
    """Acha um estágio de Lead cujo nome CONTENHA o texto dado — cobre
    convenções de prefixo tipo "[NEW] Inscrito Pro Evento". Não tenta criar
    via API (crm.status.add se mostrou instável) — se não achar, para e
    pede pra criar manualmente pelo Kanban de Leads."""
    statuses = bitrix_call("crm.status.list", {"filter": {"ENTITY_ID": "STATUS"}})
    for status in statuses:
        if name_contains in (status.get("NAME") or ""):
            print(f"Estágio '{name_contains}' já existe: {status['STATUS_ID']} (nome completo: \"{status.get('NAME')}\")")
            return status["STATUS_ID"]

    raise RuntimeError(
        f"Não achei nenhum estágio de Lead com \"{name_contains}\" no nome. "
        "Crie a etapa pelo Kanban de Leads (com o mesmo prefixo/convenção que vocês já usam) e rode de novo."
    )


def main() -> None:
    nome_evento_code = create_string_field("NOME_DO_EVENTO", "Nome do evento")
    sympla_event_id_code = create_string_field("SYMPLA_EVENT_ID", "ID do evento Sympla (técnico)")
    # "Data do evento" não é mais gerenciado por este script: o código do
    # campo foi trocado manualmente pra UF_CRM_1785161309 (fora da
    # convenção UF_CRM_DATA_DO_EVENTO), então a checagem por FIELD_NAME
    # exato não acha ele e cria um duplicado vazio. BITRIX_FIELD_DATA_DO_EVENTO
    # já está setado direto no .env/secrets com o código certo.
    origem_code = create_enum_field(
        "ORIGEM",
        "Origem",
        [ORIGEM_VALOR_FORMULARIO, ORIGEM_VALOR_INSCRITO_DESCONHECIDO, ORIGEM_VALOR_CUPOM_DESCONTO, ORIGEM_VALOR_TRAFEGO_PAGO],
    )
    presente_code = create_enum_field("PRESENTE_NO_EVENTO", "Presente no evento", [VALOR_PRESENTE, VALOR_NAO_PRESENTE])

    # Lista/enumeration com TODOS os eventos (passados e futuros), pra
    # aparecer como checkbox de múltipla seleção na aba de Filtros da
    # listagem de Leads. Diferente de ORIGEM/PRESENTE_NO_EVENTO (valores
    # fixos), essa lista cresce em runtime — automacao_a_inscricoes.py
    # adiciona um item novo por evento novo via common.ensure_enum_value().
    # Aqui só pré-populamos com o que já existe, em ordem cronológica.
    eventos = sorted(get_all_events(), key=lambda e: (e.get("start_date") or ""))
    labels_evento = [format_event_label(e.get("name", ""), (e.get("start_date") or "")[:10]) for e in eventos]
    filtrar_evento_code = create_enum_field("FILTRAR_EVENTO", "Filtrar Evento", labels_evento)

    stage_code = ensure_lead_stage("Inscrito Pro Evento")

    print()
    print("Cole no .env:")
    print(f"BITRIX_STAGE_INSCRITO_PRO_EVENTO={stage_code}")
    print("BITRIX_FIELD_DATA_DO_EVENTO=UF_CRM_1785161309  # já setado, gerenciado manualmente")
    print(f"BITRIX_FIELD_NOME_DO_EVENTO={nome_evento_code}")
    print(f"BITRIX_FIELD_SYMPLA_EVENT_ID={sympla_event_id_code}")
    print(f"BITRIX_FIELD_ORIGEM={origem_code}")
    print(f"BITRIX_FIELD_PRESENTE_NO_EVENTO={presente_code}")
    print(f"BITRIX_FIELD_FILTRAR_EVENTO={filtrar_evento_code}")


if __name__ == "__main__":
    main()
