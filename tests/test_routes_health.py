from interface import create_app


def test_health_retorna_200_sem_login():
    app = create_app()
    app.testing = True
    resp = app.test_client().get("/health")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
