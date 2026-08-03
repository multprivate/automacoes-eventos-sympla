from services import lead_sync_service


def test_filtra_evento_inativo(monkeypatch):
    monkeypatch.setattr(
        lead_sync_service.eventos_config_repo,
        "get_all",
        lambda: [{"sympla_event_id": "e1", "ativo": False, "removido_em": None}],
    )
    events = [{"id": "e1"}, {"id": "e2"}]
    result = lead_sync_service._filter_eventos_ativos(events)
    assert [e["id"] for e in result] == ["e2"]


def test_filtra_evento_removido(monkeypatch):
    monkeypatch.setattr(
        lead_sync_service.eventos_config_repo,
        "get_all",
        lambda: [{"sympla_event_id": "e1", "ativo": True, "removido_em": "2026-01-01T00:00:00Z"}],
    )
    events = [{"id": "e1"}, {"id": "e2"}]
    result = lead_sync_service._filter_eventos_ativos(events)
    assert [e["id"] for e in result] == ["e2"]


def test_evento_sem_config_e_tratado_como_ativo(monkeypatch):
    monkeypatch.setattr(lead_sync_service.eventos_config_repo, "get_all", lambda: [])
    events = [{"id": "e1"}, {"id": "e2"}]
    result = lead_sync_service._filter_eventos_ativos(events)
    assert result == events


def test_falha_ao_ler_eventos_config_e_fail_aberto(monkeypatch):
    def _raise():
        raise RuntimeError("supabase fora do ar")

    monkeypatch.setattr(lead_sync_service.eventos_config_repo, "get_all", _raise)
    events = [{"id": "e1"}, {"id": "e2"}]
    result = lead_sync_service._filter_eventos_ativos(events)
    assert result == events
