from common.bitrix_client import merge_enum_items_sorted


def test_lista_vazia_cria_todo_mundo_sem_id_na_ordem_dada():
    resultado = merge_enum_items_sorted([], ["C", "B", "A"])
    assert resultado == [
        {"VALUE": "C", "SORT": 10},
        {"VALUE": "B", "SORT": 20},
        {"VALUE": "A", "SORT": 30},
    ]


def test_reaproveita_id_de_item_existente():
    current = [{"ID": "5", "VALUE": "A", "SORT": 500}]
    resultado = merge_enum_items_sorted(current, ["A"])
    assert resultado == [{"VALUE": "A", "SORT": 10, "ID": "5"}]


def test_reordena_itens_existentes_conforme_ordered_values():
    """current está na ordem A, B (SORT antigo) -- ordered_values pede B
    primeiro, depois A. O resultado tem que respeitar a ordem NOVA, não a
    antiga, preservando os IDs de cada um."""
    current = [
        {"ID": "1", "VALUE": "A", "SORT": 10},
        {"ID": "2", "VALUE": "B", "SORT": 20},
    ]
    resultado = merge_enum_items_sorted(current, ["B", "A"])
    assert resultado == [
        {"VALUE": "B", "SORT": 10, "ID": "2"},
        {"VALUE": "A", "SORT": 20, "ID": "1"},
    ]


def test_mistura_existentes_com_novo_no_meio_da_ordem():
    current = [{"ID": "1", "VALUE": "Antigo", "SORT": 10}]
    resultado = merge_enum_items_sorted(current, ["Novo", "Antigo"])
    assert resultado == [
        {"VALUE": "Novo", "SORT": 10},
        {"VALUE": "Antigo", "SORT": 20, "ID": "1"},
    ]


def test_valor_que_sumiu_de_ordered_values_fica_preservado_no_fim():
    """Não deveria acontecer (a Sympla não perde evento), mas por
    segurança um valor que já existia e não está mais em ordered_values
    não pode desaparecer silenciosamente -- vai pro fim da lista."""
    current = [
        {"ID": "1", "VALUE": "Orfao", "SORT": 10},
        {"ID": "2", "VALUE": "Atual", "SORT": 20},
    ]
    resultado = merge_enum_items_sorted(current, ["Atual"])
    assert resultado == [
        {"VALUE": "Atual", "SORT": 10, "ID": "2"},
        {"ID": "1", "VALUE": "Orfao", "SORT": 20},
    ]


def test_valores_duplicados_no_current_preserva_todos_os_ids_sem_perder_nenhum():
    """Achado de code review: se o campo já tiver duas entradas com o
    mesmo VALUE (dado sujo pré-existente, ex: duplicata criada
    manualmente), nenhuma das duas IDs pode desaparecer -- um Lead pode
    apontar pra qualquer uma delas."""
    current = [
        {"ID": "1", "VALUE": "X", "SORT": 10},
        {"ID": "2", "VALUE": "X", "SORT": 20},
    ]
    resultado = merge_enum_items_sorted(current, ["X"])
    assert {item.get("ID") for item in resultado} == {"1", "2"}
    assert len(resultado) == 2


def test_ordered_values_com_valor_repetido_nao_duplica_a_mesma_id():
    """Achado de code review: se o chamador passar o mesmo valor duas
    vezes em ordered_values (ex: dois eventos formatados pro mesmo
    texto), o resultado não pode ter duas entradas reaproveitando a
    MESMA ID -- isso seria um payload invalido pro Bitrix."""
    current = [{"ID": "9", "VALUE": "X", "SORT": 10}]
    resultado = merge_enum_items_sorted(current, ["X", "X"])
    assert resultado == [{"VALUE": "X", "SORT": 10, "ID": "9"}]


def test_ja_na_ordem_certa_produz_payload_identico_em_valor_e_id():
    current = [
        {"ID": "1", "VALUE": "A", "SORT": 10},
        {"ID": "2", "VALUE": "B", "SORT": 20},
    ]
    resultado = merge_enum_items_sorted(current, ["A", "B"])
    assert [(r["VALUE"], r.get("ID")) for r in resultado] == [("A", "1"), ("B", "2")]
