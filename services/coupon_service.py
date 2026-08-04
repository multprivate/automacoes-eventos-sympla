"""
Resolve cupom -> assessor/origem consultando a tabela `assessores_cupom`
no Supabase, com fallback pros dicts fixos em domain/coupons.py quando o
Supabase não está configurado, está fora do ar, ou a tabela está vazia —
a automação nunca trava por causa do painel de administração estar down.

Mantém resolve_assessor_and_origem(cupom) com a mesma assinatura de
sempre: automacao_a_inscricoes.py (e, por tabela, preview_novos_leads.py)
continuam chamando exatamente como chamavam quando o mapa era só os dicts
hardcoded.
"""

import logging
import time

from domain.coupons import (
    _DEFAULT_ASSESSOR_POR_CUPOM,
    _DEFAULT_ORIGEM_POR_CUPOM_CANAL,
    resolve_assessor_and_origem as _resolve_assessor_and_origem,
)
from repositories import coupons_repo
from repositories.supabase_client import SupabaseUnavailable

log = logging.getLogger("services.coupon_service")

CACHE_TTL_SECONDS = 60

_cache: tuple[dict[str, str], dict[str, str]] | None = None
_cache_loaded_at: float = 0.0


def _rows_to_maps(rows: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    assessor_map: dict[str, str] = {}
    canal_map: dict[str, str] = {}
    for row in rows:
        cupom = row.get("cupom")
        if not cupom:
            continue
        if row.get("tipo") == "assessor" and row.get("email_assessor"):
            assessor_map[cupom] = row["email_assessor"]
        elif row.get("tipo") == "canal" and row.get("origem_canal"):
            canal_map[cupom] = row["origem_canal"]
    return assessor_map, canal_map


def load_coupon_maps(force_refresh: bool = False) -> tuple[dict[str, str], dict[str, str]]:
    """Retorna (assessor_por_cupom, origem_por_cupom_canal). Cacheia em
    processo por CACHE_TTL_SECONDS pra não bater no Supabase uma vez por
    participante — um único load por execução da Automação A, na prática."""
    global _cache, _cache_loaded_at

    if not force_refresh and _cache is not None and (time.time() - _cache_loaded_at) < CACHE_TTL_SECONDS:
        return _cache

    try:
        rows = coupons_repo.list_coupons()
    except SupabaseUnavailable:
        log.info("Supabase não configurado — usando mapa de cupons fixo no código.")
        _cache = (dict(_DEFAULT_ASSESSOR_POR_CUPOM), dict(_DEFAULT_ORIGEM_POR_CUPOM_CANAL))
        _cache_loaded_at = time.time()
        return _cache
    except Exception as exc:
        log.warning("Falha ao consultar assessores_cupom no Supabase (%s) — usando fallback fixo no código.", exc)
        _cache = (dict(_DEFAULT_ASSESSOR_POR_CUPOM), dict(_DEFAULT_ORIGEM_POR_CUPOM_CANAL))
        _cache_loaded_at = time.time()
        return _cache

    if not rows:
        log.warning("Tabela assessores_cupom está vazia no Supabase — usando fallback fixo no código.")
        _cache = (dict(_DEFAULT_ASSESSOR_POR_CUPOM), dict(_DEFAULT_ORIGEM_POR_CUPOM_CANAL))
    else:
        _cache = _rows_to_maps(rows)
    _cache_loaded_at = time.time()
    return _cache


def resolve_assessor_and_origem(cupom: str) -> tuple[str | None, str]:
    assessor_map, canal_map = load_coupon_maps()
    return _resolve_assessor_and_origem(cupom, assessor_map, canal_map)
