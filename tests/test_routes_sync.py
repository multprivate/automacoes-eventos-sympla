from interface import create_app
from interface import routes_sync


def _client():
    app = create_app()
    app.testing = True
    return app.test_client()


def test_sem_token_configurado_retorna_503(monkeypatch):
    monkeypatch.setattr(routes_sync, "SYNC_TRIGGER_TOKEN", "")
    resp = _client().get("/api/sync/trigger")
    assert resp.status_code == 503


def test_token_errado_retorna_401(monkeypatch):
    monkeypatch.setattr(routes_sync, "SYNC_TRIGGER_TOKEN", "segredo-certo")
    resp = _client().get("/api/sync/trigger?token=segredo-errado")
    assert resp.status_code == 401


def test_sem_token_na_query_retorna_401(monkeypatch):
    monkeypatch.setattr(routes_sync, "SYNC_TRIGGER_TOKEN", "segredo-certo")
    resp = _client().get("/api/sync/trigger")
    assert resp.status_code == 401


def test_token_certo_roda_a_sincronizacao(monkeypatch):
    monkeypatch.setattr(routes_sync, "SYNC_TRIGGER_TOKEN", "segredo-certo")
    stats = {"eventos_processados": 2, "leads_criados": 0, "leads_atualizados": 1, "erros": 0}
    monkeypatch.setattr(routes_sync, "sync_all_upcoming_events", lambda: stats)

    resp = _client().get("/api/sync/trigger?token=segredo-certo")

    assert resp.status_code == 200
    assert resp.get_json() == stats


def test_token_certo_via_header(monkeypatch):
    monkeypatch.setattr(routes_sync, "SYNC_TRIGGER_TOKEN", "segredo-certo")
    monkeypatch.setattr(routes_sync, "sync_all_upcoming_events", lambda: {"ok": True})

    resp = _client().get("/api/sync/trigger", headers={"X-Sync-Token": "segredo-certo"})

    assert resp.status_code == 200
