import pytest

from repositories.supabase_client import SupabaseUnavailable
from services import config_service


@pytest.fixture(autouse=True)
def _reset_cache():
    config_service._cache = None
    config_service._cache_loaded_at = 0.0
    yield
    config_service._cache = None
    config_service._cache_loaded_at = 0.0


def test_usa_supabase_quando_disponivel(monkeypatch):
    monkeypatch.setattr(
        config_service.config_repo,
        "get_all",
        lambda: {"FIELD_DATA_DO_EVENTO": "UF_CRM_TESTE"},
    )
    cfg = config_service.load_config()
    assert cfg["FIELD_DATA_DO_EVENTO"] == "UF_CRM_TESTE"


def test_chave_ausente_no_supabase_cai_pro_default(monkeypatch):
    """Uma chave faltando na tabela não derruba as outras — cada chave cai
    pro seu próprio default individualmente."""
    monkeypatch.setattr(
        config_service.config_repo,
        "get_all",
        lambda: {"FIELD_DATA_DO_EVENTO": "UF_CRM_TESTE"},
    )
    cfg = config_service.load_config()
    assert cfg["FIELD_NOME_DO_EVENTO"] == config_service._DEFAULTS["FIELD_NOME_DO_EVENTO"]


def test_cai_pro_fallback_quando_supabase_nao_configurado(monkeypatch):
    def _raise():
        raise SupabaseUnavailable("sem credencial")

    monkeypatch.setattr(config_service.config_repo, "get_all", _raise)
    cfg = config_service.load_config()
    assert cfg == config_service._DEFAULTS


def test_cai_pro_fallback_em_erro_de_rede(monkeypatch):
    def _raise():
        raise RuntimeError("timeout")

    monkeypatch.setattr(config_service.config_repo, "get_all", _raise)
    cfg = config_service.load_config()
    assert cfg == config_service._DEFAULTS


def test_cache_evita_bater_no_supabase_de_novo(monkeypatch):
    calls = {"n": 0}

    def _get_all():
        calls["n"] += 1
        return {}

    monkeypatch.setattr(config_service.config_repo, "get_all", _get_all)
    config_service.load_config()
    config_service.load_config()
    assert calls["n"] == 1


def test_getters_individuais(monkeypatch):
    monkeypatch.setattr(
        config_service.config_repo,
        "get_all",
        lambda: {"STAGE_INSCRITO_PRO_EVENTO": "OUTRO_ESTAGIO"},
    )
    assert config_service.get_stage_inscrito_pro_evento() == "OUTRO_ESTAGIO"
