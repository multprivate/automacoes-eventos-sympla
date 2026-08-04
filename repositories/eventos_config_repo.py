"""
Acesso à tabela `eventos_config` — liga/desliga por evento (Ativo/Inativo
e "Remover" na aba Eventos do painel) e os contadores/timestamp de
sincronização que alimentam o Dashboard.
"""

from datetime import datetime, timezone

from . import supabase_client

TABLE = "eventos_config"


def get_all() -> list[dict]:
    """Levanta supabase_client.SupabaseUnavailable ou
    requests.RequestException — quem chama (services/lead_sync_service.py)
    decide cair pro fail-OPEN (tratar todos os eventos como ativos)."""
    return supabase_client.select(TABLE, {"select": "*"})


def upsert_sync_result(sympla_event_id: str, nome_evento: str, data_evento: str, inscritos_count: int, presentes_count: int) -> dict:
    """Atualiza nome/data/contadores/último-sync ao final de cada
    sincronização de um evento — não mexe em ativo/removido_em (upsert
    parcial: só as colunas passadas aqui são sobrescritas)."""
    row = {
        "sympla_event_id": sympla_event_id,
        "nome_evento": nome_evento,
        "data_evento": data_evento or None,
        "inscritos_count": inscritos_count,
        "presentes_count": presentes_count,
        "ultimo_sync_em": datetime.now(timezone.utc).isoformat(),
    }
    return supabase_client.upsert(TABLE, [row], on_conflict="sympla_event_id")[0]


def set_ativo(sympla_event_id: str, ativo: bool) -> dict:
    return supabase_client.upsert(TABLE, [{"sympla_event_id": sympla_event_id, "ativo": ativo}], on_conflict="sympla_event_id")[0]


def set_removido(sympla_event_id: str, removido: bool) -> dict:
    removido_em = datetime.now(timezone.utc).isoformat() if removido else None
    return supabase_client.upsert(TABLE, [{"sympla_event_id": sympla_event_id, "removido_em": removido_em}], on_conflict="sympla_event_id")[0]
