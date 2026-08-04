"""
Mapeamentos extras de campo: o usuário define, pela aba Mapeamento do
painel, que um dado já extraído do participante (cupom, telefone, nome,
e-mail) deve ir pra um campo Bitrix específico — sem precisar de ajuste
de código a cada campo novo.

ORIGENS_DISPONIVEIS é a lista FECHADA de dados que o motor sabe extrair
de um participante — isto não é mapeamento arbitrário de qualquer coisa,
é "escolha pra qual campo Bitrix cada um desses valores já conhecidos
deveria ir". Só o código do campo Bitrix é livre.
"""

ORIGENS_DISPONIVEIS = {
    "cupom_desconto": "Cupom de desconto (texto usado na inscrição)",
    "telefone": "Telefone formatado (+55DDDNUMERO)",
    "nome_completo": "Nome completo do participante",
    "email": "E-mail do participante",
}


def resolve_extra_fields(valores: dict[str, str], mapeamentos: list[dict], lead: dict | None = None, force: bool = False) -> dict:
    """valores: {origem_dado: valor_atual_do_participante}.

    mapeamentos: linhas de mapeamentos_campos (origem_dado,
    bitrix_field_code, aplicar_em, ativo).

    lead: o Lead já existente (pra diff, idempotência) — None quando o
    Lead está sendo CRIADO (nesse caso não tem o que diffar, sempre inclui
    se houver valor).

    aplicar_em='novo' só entra quando lead is None (criação). 'todos'
    entra tanto na criação quanto na atualização de um Lead existente,
    respeitando diff (a menos que force=True)."""
    fields: dict[str, str] = {}
    for mapeamento in mapeamentos:
        if not mapeamento.get("ativo", True):
            continue

        origem_dado = mapeamento.get("origem_dado")
        campo = mapeamento.get("bitrix_field_code")
        aplicar_em = mapeamento.get("aplicar_em")
        if not origem_dado or not campo:
            continue

        valor = valores.get(origem_dado)
        if not valor:
            continue

        if aplicar_em == "novo" and lead is not None:
            continue

        if lead is not None and not force and lead.get(campo) == valor:
            continue

        fields[campo] = valor

    return fields
