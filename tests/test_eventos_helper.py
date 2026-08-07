from interface import eventos_helper


def test_uniao_de_evento_ja_sincronizado_com_futuro_novo(monkeypatch):
    monkeypatch.setattr(
        eventos_helper.eventos_config_repo,
        "get_all",
        lambda: [
            {
                "sympla_event_id": "evt_passado",
                "nome_evento": "Evento Passado",
                "data_evento": "2026-01-10",
                "inscritos_count": 5,
                "presentes_count": 3,
                "ultimo_sync_em": "2026-01-11T00:00:00+00:00",
                "ativo": True,
                "removido_em": None,
            }
        ],
    )
    monkeypatch.setattr(
        eventos_helper,
        "list_upcoming_events",
        lambda: [{"id": "evt_futuro_novo", "name": "Evento Futuro Novo", "start_date": "2026-12-01T18:00:00-03:00"}],
    )

    view = eventos_helper.list_all_events_view()
    ids = {e["id"] for e in view}

    assert ids == {"evt_passado", "evt_futuro_novo"}

    passado = next(e for e in view if e["id"] == "evt_passado")
    assert passado["sincronizavel"] is False
    assert passado["inscritos"] == 5

    novo = next(e for e in view if e["id"] == "evt_futuro_novo")
    assert novo["sincronizavel"] is True
    assert novo["ultimo_sync"] is None


def test_evento_ja_sincronizado_e_ainda_futuro_fica_sincronizavel(monkeypatch):
    monkeypatch.setattr(
        eventos_helper.eventos_config_repo,
        "get_all",
        lambda: [
            {
                "sympla_event_id": "evt_1",
                "nome_evento": "Nome Antigo",
                "data_evento": "2026-12-01",
                "inscritos_count": 1,
                "presentes_count": 0,
                "ultimo_sync_em": "2026-11-01T00:00:00+00:00",
                "ativo": True,
                "removido_em": None,
            }
        ],
    )
    monkeypatch.setattr(
        eventos_helper,
        "list_upcoming_events",
        lambda: [{"id": "evt_1", "name": "Nome Novo Vindo da Sympla", "start_date": "2026-12-01T18:00:00-03:00"}],
    )

    view = eventos_helper.list_all_events_view()

    assert len(view) == 1
    assert view[0]["sincronizavel"] is True
    assert view[0]["nome"] == "Nome Novo Vindo da Sympla"
