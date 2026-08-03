"""
Acesso a `execucoes_log` (1 linha por execução completa, alimenta os tiles
agregados do Dashboard) e `execucoes_log_itens` (1 linha por ação — sync de
um evento, remoção, toggle — alimenta a aba Logs, com os filtros
Todas/Participante/Evento).

Escritas aqui são sempre "melhor esforço": uma falha ao gravar log nunca
pode derrubar a sincronização de verdade (usa supabase_client.
insert_best_effort, que já engole erro e só loga um warning).
"""

from datetime import datetime, timezone

from . import supabase_client

TABLE_EXECUCOES = "execucoes_log"
TABLE_ITENS = "execucoes_log_itens"

_PAGE_SIZE_DEFAULT = 50


def insert_execucao(automacao: str, iniciado_em: datetime, finalizado_em: datetime, status: str, stats: dict, detalhes: dict | None = None) -> None:
    row = {
        "automacao": automacao,
        "iniciado_em": iniciado_em.isoformat(),
        "finalizado_em": finalizado_em.isoformat(),
        "status": status,
        "eventos_processados": stats.get("eventos_processados", 0),
        "leads_criados": stats.get("leads_criados", 0),
        "leads_atualizados": stats.get("leads_atualizados", 0),
        "erros": stats.get("erros", 0),
        "detalhes": detalhes,
    }
    supabase_client.insert_best_effort(TABLE_EXECUCOES, row)


def insert_item(acao: str, entidade_tipo: str, entidade_ref: str, status: str, duracao_ms: int, sympla_event_id: str | None = None, erro: str | None = None, detalhes: dict | None = None, execucao_id: int | None = None) -> None:
    row = {
        "execucao_id": execucao_id,
        "acao": acao,
        "entidade_tipo": entidade_tipo,
        "entidade_ref": entidade_ref,
        "sympla_event_id": sympla_event_id,
        "status": status,
        "duracao_ms": duracao_ms,
        "erro": erro,
        "detalhes": detalhes,
        "criado_em": datetime.now(timezone.utc).isoformat(),
    }
    supabase_client.insert_best_effort(TABLE_ITENS, row)


def list_recent_execucoes(limit: int = 20) -> list[dict]:
    return supabase_client.select(TABLE_EXECUCOES, {"select": "*", "order": "id.desc", "limit": str(limit)})


def list_itens(entidade_tipo: str | None = None, page: int = 1, page_size: int = _PAGE_SIZE_DEFAULT) -> list[dict]:
    params = {"select": "*", "order": "criado_em.desc", "limit": str(page_size), "offset": str((page - 1) * page_size)}
    if entidade_tipo:
        params["entidade_tipo"] = f"eq.{entidade_tipo}"
    return supabase_client.select(TABLE_ITENS, params)
