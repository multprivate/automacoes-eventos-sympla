"""
Acesso à tabela `participantes_processados` — substitui
.cache/sympla_processed.json como mecanismo de idempotência da Automação A.

Ao contrário de coupons_repo/config_repo (que falham ABERTO pro fallback
hardcoded), este repositório é usado com fallback FECHADO por quem chama
(services/lead_sync_service.py): se a leitura falhar, o evento inteiro é
pulado naquela rodada, nunca tratado como "ninguém foi processado ainda"
— ver rationale no plano (Fase 3).
"""

from . import supabase_client

TABLE = "participantes_processados"

# PostgREST pagina em 1000 linhas por padrão — eventos com mais inscritos
# que isso precisam de paginação explícita, mesmo padrão de bitrix_list_all.
_PAGE_SIZE = 1000


def get_processed_ids(event_id: str) -> set[str]:
    """Levanta supabase_client.SupabaseUnavailable ou
    requests.RequestException em falha — quem chama decide (fail-closed:
    pular o evento nesta rodada)."""
    ids: set[str] = set()
    offset = 0
    while True:
        rows = supabase_client.select(
            TABLE,
            {
                "select": "participant_id",
                "sympla_event_id": f"eq.{event_id}",
                "limit": str(_PAGE_SIZE),
                "offset": str(offset),
            },
        )
        ids.update(row["participant_id"] for row in rows)
        if len(rows) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return ids


def mark_processed_batch(event_id: str, participant_ids: set[str]) -> None:
    """Upsert em lote — idempotente (reenviar quem já está marcado não faz
    nada). Levanta erro em falha; quem chama decide o que fazer (a rodada
    inteira desse evento já foi feita no Bitrix, então perder o registro
    de idempotência aqui só implica reprocessar esse evento de novo na
    próxima execução, não perder o inscrito)."""
    if not participant_ids:
        return
    rows = [{"sympla_event_id": event_id, "participant_id": pid} for pid in participant_ids]
    supabase_client.upsert(TABLE, rows, on_conflict="sympla_event_id,participant_id")
