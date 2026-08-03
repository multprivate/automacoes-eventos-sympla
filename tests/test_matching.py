from domain.matching import find_matching_lead_ids


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
