from domain.matching import (
    choose_primary_contact_id,
    choose_primary_lead_id,
    contact_needs_new_event_lead,
    find_matching_contact_ids,
    find_matching_lead_ids,
)


def _lookups(phone_result=None, email_result=None, name_result=None):
    calls = {"phone": 0, "email": 0, "name": 0}

    def lookup_by_phone(_key):
        calls["phone"] += 1
        return phone_result or []

    def lookup_by_email(_key):
        calls["email"] += 1
        return email_result or []

    def lookup_by_name(_key):
        calls["name"] += 1
        return name_result or []

    return calls, lookup_by_phone, lookup_by_email, lookup_by_name


def _confirm_any_name(_lead_id: int) -> str:
    """get_lead_name que sempre confirma o match por e-mail — usado nos
    testes que não estão testando a defesa de nome, pra não mudar o
    comportamento esperado dos casos já existentes."""
    return "qualquer nome"


def test_acha_por_telefone_e_nao_tenta_email_nem_nome():
    calls, by_phone, by_email, by_name = _lookups(phone_result=[1, 2])
    ids, method = find_matching_lead_ids("+5585999998888", "a@b.com", "Fulano", by_phone, by_email, by_name, get_lead_name=_confirm_any_name)
    assert ids == [1, 2]
    assert method == "telefone"
    assert calls == {"phone": 1, "email": 0, "name": 0}


def test_sem_telefone_cai_pro_email_e_nao_tenta_nome():
    calls, by_phone, by_email, by_name = _lookups(email_result=[3])
    ids, method = find_matching_lead_ids("", "a@b.com", "Fulano", by_phone, by_email, by_name, get_lead_name=lambda _id: "Fulano")
    assert ids == [3]
    assert method == "email"
    assert calls == {"phone": 0, "email": 1, "name": 0}


def test_telefone_sem_resultado_cai_pro_email():
    calls, by_phone, by_email, by_name = _lookups(phone_result=[], email_result=[3])
    ids, method = find_matching_lead_ids("+5585999998888", "a@b.com", "Fulano", by_phone, by_email, by_name, get_lead_name=lambda _id: "Fulano")
    assert ids == [3]
    assert method == "email"
    assert calls == {"phone": 1, "email": 1, "name": 0}


def test_sem_telefone_e_sem_email_cai_pro_nome():
    calls, by_phone, by_email, by_name = _lookups(name_result=[7])
    ids, method = find_matching_lead_ids("", "", "Fulano de Tal", by_phone, by_email, by_name, get_lead_name=_confirm_any_name)
    assert ids == [7]
    assert method == "nome"
    assert calls == {"phone": 0, "email": 0, "name": 1}


def test_nenhum_criterio_bate():
    calls, by_phone, by_email, by_name = _lookups()
    ids, method = find_matching_lead_ids("+5585999998888", "a@b.com", "Fulano", by_phone, by_email, by_name, get_lead_name=_confirm_any_name)
    assert ids == []
    assert method is None
    assert calls == {"phone": 1, "email": 1, "name": 1}


def test_email_bate_mas_nome_diferente_rejeita_e_cai_pro_nome():
    """Caso real: vários inscritos distintos compartilham o e-mail do
    comprador/organizador (ex: cupom de cortesia em grupo). O candidato
    achado por e-mail tem nome diferente do inscrito -> não é a mesma
    pessoa, cai pro passo de busca por nome (que aqui não acha nada, então
    o inscrito acabaria virando um Lead novo)."""
    calls, by_phone, by_email, by_name = _lookups(email_result=[3])
    ids, method = find_matching_lead_ids(
        "", "grupo@exemplo.com", "Natan Prado", by_phone, by_email, by_name,
        get_lead_name=lambda _id: "Gabriel Prado",
    )
    assert ids == []
    assert method is None
    assert calls == {"phone": 0, "email": 1, "name": 1}


def test_email_bate_com_dois_candidatos_so_um_com_nome_confere():
    calls, by_phone, by_email, by_name = _lookups(email_result=[3, 4])
    names = {3: "Gabriel Prado", 4: "Natan Prado"}
    ids, method = find_matching_lead_ids(
        "", "grupo@exemplo.com", "Natan Prado", by_phone, by_email, by_name,
        get_lead_name=lambda lead_id: names[lead_id],
    )
    assert ids == [4]
    assert method == "email"
    assert calls == {"phone": 0, "email": 1, "name": 0}


def test_email_bate_mas_sem_nome_no_inscrito_aceita_sem_confirmar():
    """Sem nome no inscrito não há sinal pra rejeitar -> mantém o
    comportamento antigo (aceita o match por e-mail)."""
    calls, by_phone, by_email, by_name = _lookups(email_result=[3])
    ids, method = find_matching_lead_ids(
        "", "a@b.com", "", by_phone, by_email, by_name,
        get_lead_name=lambda _id: "Qualquer Nome",
    )
    assert ids == [3]
    assert method == "email"
    assert calls == {"phone": 0, "email": 1, "name": 0}


def _contact_lookups(phone_result=None, email_result=None):
    calls = {"phone": 0, "email": 0}

    def lookup_by_phone(_key):
        calls["phone"] += 1
        return phone_result or []

    def lookup_by_email(_key):
        calls["email"] += 1
        return email_result or []

    return calls, lookup_by_phone, lookup_by_email


def test_contato_acha_por_telefone_e_nao_tenta_email():
    calls, by_phone, by_email = _contact_lookups(phone_result=[10])
    ids, method = find_matching_contact_ids("+5585999998888", "a@b.com", by_phone, by_email)
    assert ids == [10]
    assert method == "telefone"
    assert calls == {"phone": 1, "email": 0}


def test_contato_sem_telefone_cai_pro_email():
    calls, by_phone, by_email = _contact_lookups(email_result=[20])
    ids, method = find_matching_contact_ids("", "a@b.com", by_phone, by_email)
    assert ids == [20]
    assert method == "email"
    assert calls == {"phone": 0, "email": 1}


def test_contato_sem_match_nao_tenta_nome():
    """Diferente da cascata de Lead: Contato não tem fallback por nome —
    a função nem recebe um lookup_by_name pra tentar."""
    calls, by_phone, by_email = _contact_lookups()
    ids, method = find_matching_contact_ids("+5585999998888", "a@b.com", by_phone, by_email)
    assert ids == []
    assert method is None
    assert calls == {"phone": 1, "email": 1}


def test_contact_needs_new_event_lead_quando_sem_lead_deste_evento():
    assert contact_needs_new_event_lead([]) is True


def test_contact_needs_new_event_lead_quando_ja_tem_lead_deste_evento():
    assert contact_needs_new_event_lead([123]) is False


def test_choose_primary_contact_id_escolhe_o_menor():
    assert choose_primary_contact_id([538, 25216]) == 538
    assert choose_primary_contact_id([16490, 158]) == 158


def test_choose_primary_contact_id_com_um_so():
    assert choose_primary_contact_id([42]) == 42


class TestChoosePrimaryLeadId:
    def test_vinculo_spa_vence_tudo(self):
        primary, secondary = choose_primary_lead_id(
            1, 2, tem_vinculo_spa_a=False, tem_vinculo_spa_b=True,
            tem_email_a=True, tem_email_b=False, activities_a=10, activities_b=0,
        )
        assert (primary, secondary) == (2, 1)

    def test_sem_vinculo_spa_email_desempata(self):
        primary, secondary = choose_primary_lead_id(
            1, 2, tem_vinculo_spa_a=False, tem_vinculo_spa_b=False,
            tem_email_a=False, tem_email_b=True, activities_a=10, activities_b=0,
        )
        assert (primary, secondary) == (2, 1)

    def test_sem_vinculo_e_sem_email_activities_desempata(self):
        primary, secondary = choose_primary_lead_id(
            1, 2, tem_vinculo_spa_a=False, tem_vinculo_spa_b=False,
            tem_email_a=False, tem_email_b=False, activities_a=1, activities_b=5,
        )
        assert (primary, secondary) == (2, 1)

    def test_tudo_igual_menor_id_vence(self):
        primary, secondary = choose_primary_lead_id(
            55164, 55162, tem_vinculo_spa_a=False, tem_vinculo_spa_b=False,
            tem_email_a=False, tem_email_b=False, activities_a=0, activities_b=0,
        )
        assert (primary, secondary) == (55162, 55164)
