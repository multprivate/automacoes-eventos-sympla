from domain.matching import (
    choose_primary_contact_id,
    choose_primary_lead_id,
    contact_needs_new_event_lead,
    find_matching_contact_ids,
    find_matching_lead_ids,
    names_are_compatible,
)


class TestNamesAreCompatible:
    def test_nome_curto_confirma_contra_nome_completo(self):
        """Caso real: inscrito digitou 'Kelly Sabina' no Sympla, o Lead já
        cadastrado tem o nome completo 'KELLY SABINA PASSOS SANTOS' —
        igualdade exata rejeitaria isso e criaria um Lead duplicado."""
        assert names_are_compatible("Kelly Sabina", "KELLY SABINA PASSOS SANTOS") is True
        assert names_are_compatible("Renato Pierot Filho", "Renato Pierot ") is True

    def test_nomes_diferentes_sao_incompativeis(self):
        assert names_are_compatible("Natan Prado", "Gabriel Prado") is False
        assert names_are_compatible("Luana Cruz", "Vitor Barros") is False

    def test_nao_aceita_substring_bruta_sem_ser_palavra_inteira(self):
        """'ana' aparece dentro de 'mariana' como substring, mas são nomes
        de pessoas diferentes — a comparação é por palavra inteira."""
        assert names_are_compatible("Ana", "Mariana Costa") is False

    def test_vazio_e_sempre_incompativel(self):
        assert names_are_compatible("", "Fulano") is False
        assert names_are_compatible("Fulano", "") is False
        assert names_are_compatible("", "") is False


def _lookups(cpf_result=None, phone_result=None, email_result=None, name_result=None):
    calls = {"cpf": 0, "phone": 0, "email": 0, "name": 0}

    def lookup_by_cpf(_key):
        calls["cpf"] += 1
        return cpf_result or []

    def lookup_by_phone(_key):
        calls["phone"] += 1
        return phone_result or []

    def lookup_by_email(_key):
        calls["email"] += 1
        return email_result or []

    def lookup_by_name(_key):
        calls["name"] += 1
        return name_result or []

    return calls, lookup_by_cpf, lookup_by_phone, lookup_by_email, lookup_by_name


def _confirm_any_name(_lead_id: int) -> str:
    """get_lead_name que sempre confirma o match por telefone/e-mail
    (retorna o mesmo nome usado como full_name nos testes que chamam
    isto: "Fulano") — usado nos testes que não estão testando a defesa
    de nome, pra não mudar o comportamento esperado dos casos já
    existentes."""
    return "Fulano"


def test_acha_por_cpf_e_nao_tenta_mais_nada():
    """CPF é único por pessoa por definição — não passa por confirmação
    de nome, nem cai pros próximos critérios."""
    calls, by_cpf, by_phone, by_email, by_name = _lookups(cpf_result=[1, 2])
    ids, method = find_matching_lead_ids(
        "05707711376", "+5585999998888", "a@b.com", "Fulano",
        by_cpf, by_phone, by_email, by_name, get_lead_name=lambda _id: "Nome bem diferente de Fulano",
    )
    assert ids == [1, 2]
    assert method == "cpf"
    assert calls == {"cpf": 1, "phone": 0, "email": 0, "name": 0}


def test_sem_cpf_cai_pro_telefone():
    calls, by_cpf, by_phone, by_email, by_name = _lookups(phone_result=[1, 2])
    ids, method = find_matching_lead_ids("", "+5585999998888", "a@b.com", "Fulano", by_cpf, by_phone, by_email, by_name, get_lead_name=_confirm_any_name)
    assert ids == [1, 2]
    assert method == "telefone"
    assert calls == {"cpf": 0, "phone": 1, "email": 0, "name": 0}


def test_cpf_sem_resultado_cai_pro_telefone():
    calls, by_cpf, by_phone, by_email, by_name = _lookups(cpf_result=[], phone_result=[1])
    ids, method = find_matching_lead_ids("05707711376", "+5585999998888", "a@b.com", "Fulano", by_cpf, by_phone, by_email, by_name, get_lead_name=_confirm_any_name)
    assert ids == [1]
    assert method == "telefone"
    assert calls == {"cpf": 1, "phone": 1, "email": 0, "name": 0}


def test_sem_telefone_cai_pro_email_e_nao_tenta_nome():
    calls, by_cpf, by_phone, by_email, by_name = _lookups(email_result=[3])
    ids, method = find_matching_lead_ids("", "", "a@b.com", "Fulano", by_cpf, by_phone, by_email, by_name, get_lead_name=lambda _id: "Fulano")
    assert ids == [3]
    assert method == "email"
    assert calls == {"cpf": 0, "phone": 0, "email": 1, "name": 0}


def test_telefone_sem_resultado_cai_pro_email():
    calls, by_cpf, by_phone, by_email, by_name = _lookups(phone_result=[], email_result=[3])
    ids, method = find_matching_lead_ids("", "+5585999998888", "a@b.com", "Fulano", by_cpf, by_phone, by_email, by_name, get_lead_name=lambda _id: "Fulano")
    assert ids == [3]
    assert method == "email"
    assert calls == {"cpf": 0, "phone": 1, "email": 1, "name": 0}


def test_sem_telefone_e_sem_email_cai_pro_nome():
    calls, by_cpf, by_phone, by_email, by_name = _lookups(name_result=[7])
    ids, method = find_matching_lead_ids("", "", "", "Fulano de Tal", by_cpf, by_phone, by_email, by_name, get_lead_name=_confirm_any_name)
    assert ids == [7]
    assert method == "nome"
    assert calls == {"cpf": 0, "phone": 0, "email": 0, "name": 1}


def test_nenhum_criterio_bate():
    calls, by_cpf, by_phone, by_email, by_name = _lookups()
    ids, method = find_matching_lead_ids("05707711376", "+5585999998888", "a@b.com", "Fulano", by_cpf, by_phone, by_email, by_name, get_lead_name=_confirm_any_name)
    assert ids == []
    assert method is None
    assert calls == {"cpf": 1, "phone": 1, "email": 1, "name": 1}


def test_email_bate_mas_nome_diferente_rejeita_e_cai_pro_nome():
    """Caso real: vários inscritos distintos compartilham o e-mail do
    comprador/organizador (ex: cupom de cortesia em grupo). O candidato
    achado por e-mail tem nome diferente do inscrito -> não é a mesma
    pessoa, cai pro passo de busca por nome (que aqui não acha nada, então
    o inscrito acabaria virando um Lead novo)."""
    calls, by_cpf, by_phone, by_email, by_name = _lookups(email_result=[3])
    ids, method = find_matching_lead_ids(
        "", "", "grupo@exemplo.com", "Natan Prado", by_cpf, by_phone, by_email, by_name,
        get_lead_name=lambda _id: "Gabriel Prado",
    )
    assert ids == []
    assert method is None
    assert calls == {"cpf": 0, "phone": 0, "email": 1, "name": 1}


def test_email_bate_com_dois_candidatos_so_um_com_nome_confere():
    calls, by_cpf, by_phone, by_email, by_name = _lookups(email_result=[3, 4])
    names = {3: "Gabriel Prado", 4: "Natan Prado"}
    ids, method = find_matching_lead_ids(
        "", "", "grupo@exemplo.com", "Natan Prado", by_cpf, by_phone, by_email, by_name,
        get_lead_name=lambda lead_id: names[lead_id],
    )
    assert ids == [4]
    assert method == "email"
    assert calls == {"cpf": 0, "phone": 0, "email": 1, "name": 0}


def test_email_bate_mas_sem_nome_no_inscrito_aceita_sem_confirmar():
    """Sem nome no inscrito não há sinal pra rejeitar -> mantém o
    comportamento antigo (aceita o match por e-mail)."""
    calls, by_cpf, by_phone, by_email, by_name = _lookups(email_result=[3])
    ids, method = find_matching_lead_ids(
        "", "", "a@b.com", "", by_cpf, by_phone, by_email, by_name,
        get_lead_name=lambda _id: "Qualquer Nome",
    )
    assert ids == [3]
    assert method == "email"
    assert calls == {"cpf": 0, "phone": 0, "email": 1, "name": 0}


def test_telefone_bate_com_nome_curto_confirma_contra_nome_completo_do_lead():
    """Caso real que quebrou com igualdade exata: inscrito registrado como
    'Kelly Sabina' no Sympla, Lead já cadastrado como 'KELLY SABINA PASSOS
    SANTOS' — precisa confirmar (não criar Lead duplicado)."""
    calls, by_cpf, by_phone, by_email, by_name = _lookups(phone_result=[55158])
    ids, method = find_matching_lead_ids(
        "", "+5585987697756", "kelly@exemplo.com", "Kelly Sabina", by_cpf, by_phone, by_email, by_name,
        get_lead_name=lambda _id: "KELLY SABINA PASSOS SANTOS",
    )
    assert ids == [55158]
    assert method == "telefone"


def test_telefone_bate_mas_nome_diferente_rejeita_e_cai_pro_email():
    """Caso real: Vitor Barros e Luana Cruz digitaram o MESMO telefone no
    Sympla (números distintos, mesma pessoa? não — duas pessoas reais
    diferentes) e colapsaram no mesmo Lead. O candidato achado por
    telefone tem nome diferente do inscrito -> não é a mesma pessoa, cai
    pro passo de e-mail."""
    calls, by_cpf, by_phone, by_email, by_name = _lookups(phone_result=[180], email_result=[])
    ids, method = find_matching_lead_ids(
        "", "+558588632263", "luana@exemplo.com", "Luana Cruz", by_cpf, by_phone, by_email, by_name,
        get_lead_name=lambda _id: "Vitor Barros",
    )
    assert ids == []
    assert method is None
    assert calls == {"cpf": 0, "phone": 1, "email": 1, "name": 1}


def test_telefone_bate_com_dois_candidatos_so_um_com_nome_confere():
    calls, by_cpf, by_phone, by_email, by_name = _lookups(phone_result=[170, 180])
    names = {170: "Vitor Barros", 180: "Luana Cruz"}
    ids, method = find_matching_lead_ids(
        "", "+558588632263", "luana@exemplo.com", "Luana Cruz", by_cpf, by_phone, by_email, by_name,
        get_lead_name=lambda lead_id: names[lead_id],
    )
    assert ids == [180]
    assert method == "telefone"
    assert calls == {"cpf": 0, "phone": 1, "email": 0, "name": 0}


def test_telefone_bate_mas_sem_nome_no_inscrito_aceita_sem_confirmar():
    calls, by_cpf, by_phone, by_email, by_name = _lookups(phone_result=[1])
    ids, method = find_matching_lead_ids(
        "", "+5585999998888", "a@b.com", "", by_cpf, by_phone, by_email, by_name,
        get_lead_name=lambda _id: "Qualquer Nome",
    )
    assert ids == [1]
    assert method == "telefone"
    assert calls == {"cpf": 0, "phone": 1, "email": 0, "name": 0}


def _contact_lookups(cpf_result=None, phone_result=None, email_result=None):
    calls = {"cpf": 0, "phone": 0, "email": 0}

    def lookup_by_cpf(_key):
        calls["cpf"] += 1
        return cpf_result or []

    def lookup_by_phone(_key):
        calls["phone"] += 1
        return phone_result or []

    def lookup_by_email(_key):
        calls["email"] += 1
        return email_result or []

    return calls, lookup_by_cpf, lookup_by_phone, lookup_by_email


def test_contato_acha_por_cpf_e_nao_tenta_mais_nada():
    calls, by_cpf, by_phone, by_email = _contact_lookups(cpf_result=[99])
    ids, method = find_matching_contact_ids("05707711376", "+5585999998888", "a@b.com", by_cpf, by_phone, by_email)
    assert ids == [99]
    assert method == "cpf"
    assert calls == {"cpf": 1, "phone": 0, "email": 0}


def test_contato_sem_cpf_cai_pro_telefone():
    calls, by_cpf, by_phone, by_email = _contact_lookups(phone_result=[10])
    ids, method = find_matching_contact_ids("", "+5585999998888", "a@b.com", by_cpf, by_phone, by_email)
    assert ids == [10]
    assert method == "telefone"
    assert calls == {"cpf": 0, "phone": 1, "email": 0}


def test_contato_acha_por_telefone_e_nao_tenta_email():
    calls, by_cpf, by_phone, by_email = _contact_lookups(phone_result=[10])
    ids, method = find_matching_contact_ids("", "+5585999998888", "a@b.com", by_cpf, by_phone, by_email)
    assert ids == [10]
    assert method == "telefone"
    assert calls == {"cpf": 0, "phone": 1, "email": 0}


def test_contato_sem_telefone_cai_pro_email():
    calls, by_cpf, by_phone, by_email = _contact_lookups(email_result=[20])
    ids, method = find_matching_contact_ids("", "", "a@b.com", by_cpf, by_phone, by_email)
    assert ids == [20]
    assert method == "email"
    assert calls == {"cpf": 0, "phone": 0, "email": 1}


def test_contato_sem_match_nao_tenta_nome():
    """Diferente da cascata de Lead: Contato não tem fallback por nome —
    a função nem recebe um lookup_by_name pra tentar."""
    calls, by_cpf, by_phone, by_email = _contact_lookups()
    ids, method = find_matching_contact_ids("05707711376", "+5585999998888", "a@b.com", by_cpf, by_phone, by_email)
    assert ids == []
    assert method is None
    assert calls == {"cpf": 1, "phone": 1, "email": 1}


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
