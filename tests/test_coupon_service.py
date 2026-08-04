import pytest

from repositories.supabase_client import SupabaseUnavailable
from services import coupon_service


@pytest.fixture(autouse=True)
def _reset_cache():
    """O cache de load_coupon_maps é um global de módulo — sem resetar
    entre testes, o resultado de um teste vaza pro próximo."""
    coupon_service._cache = None
    coupon_service._cache_loaded_at = 0.0
    yield
    coupon_service._cache = None
    coupon_service._cache_loaded_at = 0.0


def test_usa_supabase_quando_disponivel(monkeypatch):
    monkeypatch.setattr(
        coupon_service.coupons_repo,
        "list_coupons",
        lambda: [
            {"cupom": "100.00% - TESTE", "tipo": "assessor", "email_assessor": "teste@empresa.com", "origem_canal": None},
            {"cupom": "100.00% - CANALX", "tipo": "canal", "email_assessor": None, "origem_canal": "Canal X"},
        ],
    )
    assessor_map, canal_map = coupon_service.load_coupon_maps()
    assert assessor_map == {"100.00% - TESTE": "teste@empresa.com"}
    assert canal_map == {"100.00% - CANALX": "Canal X"}


def test_cai_pro_fallback_quando_supabase_nao_configurado(monkeypatch):
    def _raise():
        raise SupabaseUnavailable("sem credencial")

    monkeypatch.setattr(coupon_service.coupons_repo, "list_coupons", _raise)
    assessor_map, canal_map = coupon_service.load_coupon_maps()
    assert assessor_map == coupon_service._DEFAULT_ASSESSOR_POR_CUPOM
    assert canal_map == coupon_service._DEFAULT_ORIGEM_POR_CUPOM_CANAL


def test_cai_pro_fallback_em_erro_de_rede(monkeypatch):
    def _raise():
        raise RuntimeError("timeout")

    monkeypatch.setattr(coupon_service.coupons_repo, "list_coupons", _raise)
    assessor_map, canal_map = coupon_service.load_coupon_maps()
    assert assessor_map == coupon_service._DEFAULT_ASSESSOR_POR_CUPOM


def test_cai_pro_fallback_quando_tabela_vazia(monkeypatch):
    monkeypatch.setattr(coupon_service.coupons_repo, "list_coupons", lambda: [])
    assessor_map, canal_map = coupon_service.load_coupon_maps()
    assert assessor_map == coupon_service._DEFAULT_ASSESSOR_POR_CUPOM


def test_cache_evita_bater_no_supabase_de_novo(monkeypatch):
    calls = {"n": 0}

    def _list():
        calls["n"] += 1
        return [{"cupom": "X", "tipo": "assessor", "email_assessor": "a@b.com", "origem_canal": None}]

    monkeypatch.setattr(coupon_service.coupons_repo, "list_coupons", _list)
    coupon_service.load_coupon_maps()
    coupon_service.load_coupon_maps()
    coupon_service.load_coupon_maps()
    assert calls["n"] == 1


def test_force_refresh_ignora_cache(monkeypatch):
    calls = {"n": 0}

    def _list():
        calls["n"] += 1
        return []

    monkeypatch.setattr(coupon_service.coupons_repo, "list_coupons", _list)
    coupon_service.load_coupon_maps()
    coupon_service.load_coupon_maps(force_refresh=True)
    assert calls["n"] == 2


def test_resolve_assessor_and_origem_usa_mapa_carregado(monkeypatch):
    monkeypatch.setattr(
        coupon_service.coupons_repo,
        "list_coupons",
        lambda: [{"cupom": "100.00% - TESTE", "tipo": "assessor", "email_assessor": "teste@empresa.com", "origem_canal": None}],
    )
    email, origem = coupon_service.resolve_assessor_and_origem("100.00% - teste")
    assert email == "teste@empresa.com"
    assert origem == "Cupom de Desconto"
