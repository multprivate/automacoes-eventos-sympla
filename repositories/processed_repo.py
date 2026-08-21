"""
Acesso à tabela `participantes_processados` — substitui
.cache/sympla_processed.json como mecanismo de idempotência da Automação A.

Ao contrário de coupons_repo/config_repo (que falham ABERTO pro fallback
hardcoded), este repositório é usado com fallback FECHADO por quem chama
(services/lead_sync_service.py): se a leitura falhar, o evento inteiro é
pulado naquela rodada, nunca tratado como "ninguém foi processado ainda"
— ver rationale no plano (Fase 3).

Desde a migração 0006, cada linha também guarda o RESULTADO do match
daquele inscrito (cliente ou não, por qual sinal, qual card no Bitrix) —
é atributo do mesmo fato de idempotência, escrito no mesmo instante.
get_processed_ids continua fail-FECHADO (decide se reprocessa);
get_resultados é fail-ABERTO por quem chama (é dado de exibição pra aba
Inscritos, não de decisão)."""

from datetime import datetime, timezone

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


def mark_processed_batch(event_id: str, resultados: list[dict]) -> None:
    """Upsert em lote — idempotente (reenviar quem já está marcado não faz
    nada). Levanta erro em falha; quem chama decide o que fazer (a rodada
    inteira desse evento já foi feita no Bitrix, então perder o registro
    de idempotência aqui só implica reprocessar esse evento de novo na
    próxima execução, não perder o inscrito).

    Além da marca de idempotência, grava o RESULTADO do match de cada
    inscrito (services/lead_sync_service.py::process_participant, que
    retorna um dict por inscrito processado com sucesso — ver ali o
    formato de `resultados`). Monta a linha COMPLETA aqui, com None
    explícito no que não se aplica: o PostgREST rejeita upsert em lote
    com objetos de formato diferente entre si (PGRST102), e quem chama
    pode passar dicts com chaves diferentes — uniformizar é
    responsabilidade deste repositório.

    processado_em NÃO entra no payload de propósito: assim o ON CONFLICT
    preserva a PRIMEIRA data ("Data encontrado" na aba Inscritos).
    verificado_em é o par dela e é reescrito a cada rodada (sincronização
    normal ou botão "Reprocessar")."""
    if not resultados:
        return
    agora = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "sympla_event_id": event_id,
            "participant_id": str(r["participant_id"]),
            "is_cliente": r.get("is_cliente"),
            "match_method": r.get("match_method"),
            "bitrix_contact_id": r.get("bitrix_contact_id"),
            "bitrix_lead_id": r.get("bitrix_lead_id"),
            "contact_ids_duplicados": r.get("contact_ids_duplicados"),
            "verificado_em": agora,
        }
        for r in resultados
    ]
    supabase_client.upsert(TABLE, rows, on_conflict="sympla_event_id,participant_id")


def get_resultados(event_id: str) -> dict[str, dict]:
    """Todas as linhas de um evento, indexadas por participant_id —
    alimenta a aba Inscritos (interface/inscritos_helper.py). Mesma
    paginação de 1000 de get_processed_ids.

    Ao contrário de get_processed_ids, este é fail-ABERTO por quem chama:
    é dado de EXIBIÇÃO, não de decisão de idempotência — se a leitura
    falhar, a tela mostra os inscritos vindos da Sympla com tudo "não
    verificado" e um aviso, em vez de travar a página inteira."""
    rows: dict[str, dict] = {}
    offset = 0
    while True:
        page = supabase_client.select(
            TABLE,
            {
                "select": "*",
                "sympla_event_id": f"eq.{event_id}",
                "limit": str(_PAGE_SIZE),
                "offset": str(offset),
            },
        )
        rows.update({row["participant_id"]: row for row in page})
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return rows
