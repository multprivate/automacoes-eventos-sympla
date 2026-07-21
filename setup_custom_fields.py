"""
Roda uma vez só: cria os 2 campos novos no Lead que as automações
reformuladas precisam (Nome do evento, ID interno do evento Sympla) e
imprime os códigos UF_CRM_... gerados, pra colar no .env.

Uso:
    python setup_custom_fields.py
"""

from common import bitrix_call


def create_string_field(field_name: str, label: str) -> str:
    existing = bitrix_call("crm.lead.userfield.list", {"filter": {"FIELD_NAME": f"UF_CRM_{field_name}"}})
    if existing:
        code = existing[0]["FIELD_NAME"]
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


def main() -> None:
    nome_evento_code = create_string_field("NOME_DO_EVENTO", "Nome do evento")
    sympla_event_id_code = create_string_field("SYMPLA_EVENT_ID", "ID do evento Sympla (técnico)")

    print()
    print("Cole no .env:")
    print(f"BITRIX_FIELD_NOME_DO_EVENTO={nome_evento_code}")
    print(f"BITRIX_FIELD_SYMPLA_EVENT_ID={sympla_event_id_code}")


if __name__ == "__main__":
    main()
