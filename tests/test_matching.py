from domain.matching import choose_primary_contact_id, contact_needs_new_lead, find_matching_contact_ids, find_matching_lead_ids


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


def test_acha_por_telefone_e_nao_tenta_email_nem_nome():
    calls, by_phone, by_email, by_name = _lookups(phone_result=[1, 2])
    ids, method = find_matching_lead_ids("+5585999998888", "a@b.com", "Fulano", by_phone, by_email, by_name)
    assert ids == [1, 2]
    assert method == "telefone"
    assert calls == {"phone": 1, "email": 0, "name": 0}


def test_sem_telefone_cai_pro_email_e_nao_tenta_nome():
    calls, by_phone, by_email, by_name = _lookups(email_result=[3])
    ids, method = find_matching_lead_ids("", "a@b.com", "Fulano", by_phone, by_email, by_name)
    assert ids == [3]
    assert method == "email"
    assert calls == {"phone": 0, "email": 1, "name": 0}


def test_telefone_sem_resultado_cai_pro_email():
    calls, by_phone, by_email, by_name = _lookups(phone_result=[], email_result=[3])
    ids, method = find_matching_lead_ids("+5585999998888", "a@b.com", "Fulano", by_phone, by_email, by_name)
    assert ids == [3]
    assert method == "email"
    assert calls == {"phone": 1, "email": 1, "name": 0}


def test_sem_telefone_e_sem_email_cai_pro_nome():
    calls, by_phone, by_email, by_name = _lookups(name_result=[7])
    ids, method = find_matching_lead_ids("", "", "Fulano de Tal", by_phone, by_email, by_name)
    assert ids == [7]
    assert method == "nome"
    assert calls == {"phone": 0, "email": 0, "name": 1}


def test_nenhum_criterio_bate():
    calls, by_phone, by_email, by_name = _lookups()
    ids, method = find_matching_lead_ids("+5585999998888", "a@b.com", "Fulano", by_phone, by_email, by_name)
    assert ids == []
    assert method is None
    assert calls == {"phone": 1, "email": 1, "name": 1}


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


def test_contact_needs_new_lead_quando_sem_lead_aberto():
    assert contact_needs_new_lead([]) is True


def test_contact_needs_new_lead_quando_ja_tem_lead_aberto():
    assert contact_needs_new_lead([123]) is False


def test_choose_primary_contact_id_escolhe_o_menor():
    assert choose_primary_contact_id([538, 25216]) == 538
    assert choose_primary_contact_id([16490, 158]) == 158


def test_choose_primary_contact_id_com_um_so():
    assert choose_primary_contact_id([42]) == 42
