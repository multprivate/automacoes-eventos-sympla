"""
Carrega os mapeamentos extras de campo (tabela mapeamentos_campos), com
cache de processo — mesmo padrão de coupon_service.py/config_service.py.

Fail-ABERTO: se o Supabase estiver indisponível, os mapeamentos extras
simplesmente não são aplicados nesta rodada — perder um campo extra é bem
menos grave que travar a sincronização de leads por causa disso.
"""

import logging
import time

from repositories import campo_mapeamentos_repo
from repositories.supabase_client import SupabaseUnavailable

log = logging.getLogger("services.campo_mapeamento_service")

CACHE_TTL_SECONDS = 60

_cache: list[dict] | None = None
_cache_loaded_at: float = 0.0


def load_mapeamentos(force_refresh: bool = False) -> list[dict]:
    global _cache, _cache_loaded_at

    if not force_refresh and _cache is not None and (time.time() - _cache_loaded_at) < CACHE_TTL_SECONDS:
        return _cache

    try:
        _cache = campo_mapeamentos_repo.list_ativos()
    except SupabaseUnavailable:
        log.info("Supabase não configurado — sem mapeamentos extras de campo nesta rodada.")
        _cache = []
    except Exception as exc:
        log.warning("Falha ao consultar mapeamentos_campos (%s) — sem mapeamentos extras nesta rodada.", exc)
        _cache = []
    _cache_loaded_at = time.time()
    return _cache
