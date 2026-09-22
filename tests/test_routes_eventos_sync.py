"""
_run_sync (interface/routes_eventos.py) roda a sincronizacao de verdade
numa thread em segundo plano -- ver o docstring da funcao pro incidente
real (timeout de proxy) que motivou a mudanca. Estes testes garantem o
contrato que a rota depende: a trava e adquirida ANTES de retornar
(sincrono), o trabalho de verdade acontece em background, e a trava e
sempre liberada ao final (sucesso ou erro).
"""
import threading
import time

from flask import get_flashed_messages

from interface import create_app, routes_eventos
from repositories.sync_locks_repo import SyncLockHeld


def _app():
    app = create_app()
    app.testing = True
    return app


def test_run_sync_retorna_na_hora_e_termina_o_trabalho_em_background(monkeypatch):
    chamadas_trava = []
    monkeypatch.setattr(routes_eventos, "acquire_lock", lambda escopo, quem: chamadas_trava.append(("acquire", escopo, quem)))
    monkeypatch.setattr(routes_eventos, "release_lock", lambda escopo: chamadas_trava.append(("release", escopo)))

    concluiu = threading.Event()

    def fake_sync_one_event(event_id, force=False):
        assert event_id == "evt1"
        assert force is True
        concluiu.set()
        return {"leads_criados": 1, "leads_atualizados": 2, "erros": 0}

    monkeypatch.setattr(routes_eventos, "sync_one_event", fake_sync_one_event)

    with _app().test_request_context():
        routes_eventos._run_sync("evt1", force=True)
        mensagens = get_flashed_messages()

    # A trava já foi adquirida antes de _run_sync retornar -- é isso que dá
    # o feedback imediato de "já está rodando" pro clique duplo.
    assert chamadas_trava[0] == ("acquire", "evt1", "painel")
    assert any("segundo plano" in m for m in mensagens)

    assert concluiu.wait(timeout=2), "worker em background não rodou a tempo"
    for _ in range(200):
        if ("release", "evt1") in chamadas_trava:
            break
        time.sleep(0.01)
    assert ("release", "evt1") in chamadas_trava


def test_run_sync_com_trava_ja_em_uso_nao_inicia_trabalho(monkeypatch):
    def fake_acquire(escopo, quem):
        raise SyncLockHeld(f"Escopo '{escopo}' já travado por 'outro'.")

    monkeypatch.setattr(routes_eventos, "acquire_lock", fake_acquire)
    chamado = []
    monkeypatch.setattr(routes_eventos, "sync_one_event", lambda *a, **k: chamado.append(1))

    with _app().test_request_context():
        routes_eventos._run_sync("evt1", force=False)
        mensagens = get_flashed_messages()

    assert not chamado
    assert any("travado" in m for m in mensagens)


def test_run_sync_erro_no_worker_ainda_libera_a_trava(monkeypatch):
    chamadas_trava = []
    monkeypatch.setattr(routes_eventos, "acquire_lock", lambda escopo, quem: chamadas_trava.append(("acquire", escopo)))
    monkeypatch.setattr(routes_eventos, "release_lock", lambda escopo: chamadas_trava.append(("release", escopo)))

    def fake_sync_one_event(event_id, force=False):
        raise RuntimeError("Bitrix fora do ar")

    monkeypatch.setattr(routes_eventos, "sync_one_event", fake_sync_one_event)

    with _app().test_request_context():
        routes_eventos._run_sync("evt1", force=False)

    for _ in range(200):
        if ("release", "evt1") in chamadas_trava:
            break
        time.sleep(0.01)
    assert ("release", "evt1") in chamadas_trava
