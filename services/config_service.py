"""
Resolve os códigos de campo/estágio do Bitrix (FIELD_DATA_DO_EVENTO,
FIELD_NOME_DO_EVENTO, FIELD_SYMPLA_EVENT_ID, FIELD_ORIGEM,
FIELD_PRESENTE_NO_EVENTO, STAGE_INSCRITO_PRO_EVENTO, STAGE_POS_EVENTO)
consultando a tabela `config_kv` no Supabase, com fallback pros valores
fixos de common/constants.py (hoje vindos do .env) quando o Supabase não
está configurado, fora do ar, ou sem a chave.

Só services/lead_sync_service.py e o painel (interface/) chamam isto.

Mesmo padrão de cache/fallback já usado em services/coupon_service.py.
"""

import logging
import time

from common import (
    FIELD_CPF_CONTACT,
    FIELD_CPF_LEAD,
    FIELD_DATA_DO_EVENTO,
    FIELD_FILTRAR_EVENTO,
    FIELD_NOME_DO_EVENTO,
    FIELD_ORIGEM,
    FIELD_PRESENTE_NO_EVENTO,
    FIELD_SYMPLA_EVENT_ID,
    STAGE_INSCRITO_PRO_EVENTO,
    STAGE_POS_EVENTO,
)
from repositories import config_repo
from repositories.supabase_client import SupabaseUnavailable

log = logging.getLogger("services.config_service")

CACHE_TTL_SECONDS = 60

_DEFAULTS = {
    "FIELD_DATA_DO_EVENTO": FIELD_DATA_DO_EVENTO,
    "FIELD_NOME_DO_EVENTO": FIELD_NOME_DO_EVENTO,
    "FIELD_SYMPLA_EVENT_ID": FIELD_SYMPLA_EVENT_ID,
    "FIELD_ORIGEM": FIELD_ORIGEM,
    "FIELD_FILTRAR_EVENTO": FIELD_FILTRAR_EVENTO,
    "FIELD_PRESENTE_NO_EVENTO": FIELD_PRESENTE_NO_EVENTO,
    "FIELD_CPF_LEAD": FIELD_CPF_LEAD,
    "FIELD_CPF_CONTACT": FIELD_CPF_CONTACT,
    "STAGE_INSCRITO_PRO_EVENTO": STAGE_INSCRITO_PRO_EVENTO,
    "STAGE_POS_EVENTO": STAGE_POS_EVENTO,
}

_cache: dict[str, str] | None = None
_cache_loaded_at: float = 0.0


def load_config(force_refresh: bool = False) -> dict[str, str]:
    """Retorna o mapa chave->valor efetivo (Supabase, com fallback pro
    default de cada chave individualmente — uma chave ausente no Supabase
    não derruba as outras). Cacheia em processo por CACHE_TTL_SECONDS."""
    global _cache, _cache_loaded_at

    if not force_refresh and _cache is not None and (time.time() - _cache_loaded_at) < CACHE_TTL_SECONDS:
        return _cache

    try:
        rows = config_repo.get_all()
    except SupabaseUnavailable:
        log.info("Supabase não configurado — usando configuração fixa do .env.")
        rows = {}
    except Exception as exc:
        log.warning("Falha ao consultar config_kv no Supabase (%s) — usando configuração fixa do .env.", exc)
        rows = {}

    _cache = {chave: rows.get(chave) or default for chave, default in _DEFAULTS.items()}
    _cache_loaded_at = time.time()
    return _cache


def get_field_data_do_evento() -> str:
    return load_config()["FIELD_DATA_DO_EVENTO"]


def get_field_nome_do_evento() -> str:
    return load_config()["FIELD_NOME_DO_EVENTO"]


def get_field_sympla_event_id() -> str:
    return load_config()["FIELD_SYMPLA_EVENT_ID"]


def get_field_origem() -> str:
    return load_config()["FIELD_ORIGEM"]


def get_field_filtrar_evento() -> str:
    return load_config()["FIELD_FILTRAR_EVENTO"]


def get_field_presente_no_evento() -> str:
    return load_config()["FIELD_PRESENTE_NO_EVENTO"]


def get_field_cpf_lead() -> str:
    return load_config()["FIELD_CPF_LEAD"]


def get_field_cpf_contact() -> str:
    return load_config()["FIELD_CPF_CONTACT"]


def get_stage_inscrito_pro_evento() -> str:
    return load_config()["STAGE_INSCRITO_PRO_EVENTO"]


def get_stage_pos_evento() -> str:
    return load_config()["STAGE_POS_EVENTO"]
