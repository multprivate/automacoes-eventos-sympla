"""
Aba Inscritos: colunas "Trouxe (cupom)" e "Responsável (Bitrix)" e filtro
por assessor (interface/routes_eventos.py::_preencher_assessores). Sympla,
Bitrix e Supabase são trocados por fakes — nenhuma chamada de rede.
"""
from interface import create_app, routes_eventos


def _participante(pid: str, order_discount: str = "") -> dict:
    return {"id": pid, "first_name": f"Pessoa{pid}", "last_name": "Teste", "email": f"p{pid}@x.com", "order_discount": order_discount}


def _linhas(*lead_ids):
    return [
        {"lead_id": lead_id, "assessor_cupom": None, "responsavel_bitrix": None}
        for lead_id in lead_ids
    ]


def _patch_usuarios(monkeypatch):
    monkeypatch.setattr(
        routes_eventos,
        "get_user_names",
        lambda: ({"7": "Bruna Tassia"}, {"bruna.tassia@multprivate.seg.br": "Bruna Tassia"}),
    )
    monkeypatch.setattr(
        routes_eventos,
        "load_coupon_maps",
        lambda: ({"100.00% - BRUNA": "bruna.tassia@multprivate.seg.br"}, {}),
    )


def test_preenche_assessor_do_cupom_e_responsavel_do_lead(monkeypatch):
    _patch_usuarios(monkeypatch)
    participantes = [_participante("1", "100.00% - BRUNA"), _participante("2"), _participante("3", "CUPOM-DESCONHECIDO")]
    linhas = _linhas(10, None, 12)

    routes_eventos._preencher_assessores("evt", participantes, linhas, {"10": "7", "12": "999"})

    assert [l["assessor_cupom"] for l in linhas] == ["Bruna Tassia", None, None]
    assert [l["responsavel_bitrix"] for l in linhas] == ["Bruna Tassia", None, None]


def test_falha_ao_listar_usuarios_do_bitrix_deixa_colunas_vazias(monkeypatch):
    def boom():
        raise RuntimeError("sem permissão de usuários")

    monkeypatch.setattr(routes_eventos, "get_user_names", boom)
    linhas = _linhas(10)

    routes_eventos._preencher_assessores("evt", [_participante("1", "100.00% - BRUNA")], linhas, {"10": "7"})

    assert linhas[0]["assessor_cupom"] is None
    assert linhas[0]["responsavel_bitrix"] is None


def test_falha_no_cupom_preserva_responsavel(monkeypatch):
    _patch_usuarios(monkeypatch)

    def boom():
        raise RuntimeError("supabase fora")

    monkeypatch.setattr(routes_eventos, "load_coupon_maps", boom)
    linhas = _linhas(10)

    routes_eventos._preencher_assessores("evt", [_participante("1", "100.00% - BRUNA")], linhas, {"10": "7"})

    assert linhas[0]["responsavel_bitrix"] == "Bruna Tassia"
    assert linhas[0]["assessor_cupom"] is None


def test_pagina_inscritos_renderiza_colunas_e_filtra_por_assessor(monkeypatch):
    _patch_usuarios(monkeypatch)
    monkeypatch.setattr(routes_eventos, "get_event_or_raise", lambda event_id: {"name": "Evento X", "start_date": "2026-10-01"})
    monkeypatch.setattr(routes_eventos, "get_sympla_all_participants", lambda event_id: [_participante("1", "100.00% - BRUNA"), _participante("2")])
    monkeypatch.setattr(routes_eventos.processed_repo, "get_resultados", lambda event_id: {})
    monkeypatch.setattr(routes_eventos, "spa_find_item_by_sympla_event_id", lambda event_id: None)

    app = create_app()
    app.testing = True
    client = app.test_client()
    with client.session_transaction() as sessao:
        sessao["admin_logado"] = True

    todos = client.get("/eventos/evt/inscritos").get_data(as_text=True)
    assert "Trouxe (cupom)" in todos and "Responsável (Bitrix)" in todos
    assert "Pessoa1 Teste" in todos and "Pessoa2 Teste" in todos

    filtrado = client.get("/eventos/evt/inscritos?assessor=Bruna Tassia").get_data(as_text=True)
    assert "Pessoa1 Teste" in filtrado and "Pessoa2 Teste" not in filtrado

    sem = client.get("/eventos/evt/inscritos?assessor=__sem__").get_data(as_text=True)
    assert "Pessoa2 Teste" in sem and "Pessoa1 Teste" not in sem

    csv_resposta = client.get("/eventos/evt/inscritos/exportar.csv?assessor=Bruna Tassia").get_data(as_text=True)
    assert "assessor_cupom,responsavel_bitrix" in csv_resposta
    assert "Pessoa1 Teste" in csv_resposta and "Pessoa2 Teste" not in csv_resposta
