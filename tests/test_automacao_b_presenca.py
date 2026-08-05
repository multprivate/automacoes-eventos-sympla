import automacao_b_presenca as automacao_b


def test_acha_participante_so_por_email_quando_telefone_e_nome_nao_batem(monkeypatch):
    participantes = [
        {"id": "1", "email": "ana@example.com", "first_name": "Ana", "last_name": "Freitas", "checkin": {}},
    ]
    monkeypatch.setattr(automacao_b, "get_sympla_all_participants", lambda event_id: participantes)

    resultado = automacao_b.find_matching_participant("evt1", phone_key="", name_key="alguem-que-nao-bate", email_key="ana@example.com")

    assert resultado is not None
    assert resultado["id"] == "1"


def test_nao_acha_participante_quando_nada_bate(monkeypatch):
    participantes = [
        {"id": "1", "email": "ana@example.com", "first_name": "Ana", "last_name": "Freitas", "checkin": {}},
    ]
    monkeypatch.setattr(automacao_b, "get_sympla_all_participants", lambda event_id: participantes)

    resultado = automacao_b.find_matching_participant("evt1", phone_key="", name_key="ninguem", email_key="outro@example.com")

    assert resultado is None
