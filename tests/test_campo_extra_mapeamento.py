from domain.campo_extra_mapeamento import resolve_extra_fields

VALORES = {
    "cupom_desconto": "100.00% - IARA",
    "telefone": "+5585999998888",
    "nome_completo": "Fulano de Tal",
    "email": "fulano@empresa.com",
}


def test_aplica_em_todos_entra_na_criacao():
    mapeamentos = [{"origem_dado": "cupom_desconto", "bitrix_field_code": "UF_CRM_CUPOM", "aplicar_em": "todos", "ativo": True}]
    fields = resolve_extra_fields(VALORES, mapeamentos, lead=None)
    assert fields == {"UF_CRM_CUPOM": "100.00% - IARA"}


def test_aplica_em_todos_entra_na_atualizacao_quando_diferente():
    mapeamentos = [{"origem_dado": "cupom_desconto", "bitrix_field_code": "UF_CRM_CUPOM", "aplicar_em": "todos", "ativo": True}]
    lead = {"UF_CRM_CUPOM": "cupom antigo"}
    fields = resolve_extra_fields(VALORES, mapeamentos, lead=lead)
    assert fields == {"UF_CRM_CUPOM": "100.00% - IARA"}


def test_aplica_em_todos_nao_reenvia_se_ja_igual():
    mapeamentos = [{"origem_dado": "cupom_desconto", "bitrix_field_code": "UF_CRM_CUPOM", "aplicar_em": "todos", "ativo": True}]
    lead = {"UF_CRM_CUPOM": "100.00% - IARA"}
    fields = resolve_extra_fields(VALORES, mapeamentos, lead=lead)
    assert fields == {}


def test_force_reenvia_mesmo_ja_igual():
    mapeamentos = [{"origem_dado": "cupom_desconto", "bitrix_field_code": "UF_CRM_CUPOM", "aplicar_em": "todos", "ativo": True}]
    lead = {"UF_CRM_CUPOM": "100.00% - IARA"}
    fields = resolve_extra_fields(VALORES, mapeamentos, lead=lead, force=True)
    assert fields == {"UF_CRM_CUPOM": "100.00% - IARA"}


def test_aplica_em_novo_nao_entra_na_atualizacao():
    mapeamentos = [{"origem_dado": "cupom_desconto", "bitrix_field_code": "UF_CRM_CUPOM", "aplicar_em": "novo", "ativo": True}]
    lead = {}
    fields = resolve_extra_fields(VALORES, mapeamentos, lead=lead)
    assert fields == {}


def test_aplica_em_novo_entra_na_criacao():
    mapeamentos = [{"origem_dado": "cupom_desconto", "bitrix_field_code": "UF_CRM_CUPOM", "aplicar_em": "novo", "ativo": True}]
    fields = resolve_extra_fields(VALORES, mapeamentos, lead=None)
    assert fields == {"UF_CRM_CUPOM": "100.00% - IARA"}


def test_mapeamento_inativo_e_ignorado():
    mapeamentos = [{"origem_dado": "cupom_desconto", "bitrix_field_code": "UF_CRM_CUPOM", "aplicar_em": "todos", "ativo": False}]
    fields = resolve_extra_fields(VALORES, mapeamentos, lead=None)
    assert fields == {}


def test_valor_vazio_nao_gera_campo():
    valores = {**VALORES, "cupom_desconto": ""}
    mapeamentos = [{"origem_dado": "cupom_desconto", "bitrix_field_code": "UF_CRM_CUPOM", "aplicar_em": "todos", "ativo": True}]
    fields = resolve_extra_fields(valores, mapeamentos, lead=None)
    assert fields == {}


def test_multiplos_mapeamentos_para_origens_diferentes():
    mapeamentos = [
        {"origem_dado": "cupom_desconto", "bitrix_field_code": "UF_CRM_CUPOM", "aplicar_em": "todos", "ativo": True},
        {"origem_dado": "telefone", "bitrix_field_code": "UF_CRM_TELEFONE_2", "aplicar_em": "novo", "ativo": True},
    ]
    fields = resolve_extra_fields(VALORES, mapeamentos, lead=None)
    assert fields == {"UF_CRM_CUPOM": "100.00% - IARA", "UF_CRM_TELEFONE_2": "+5585999998888"}
