"""
Trava contra corrida entre o Cron Job agendado e um "Sincronizar agora"
disparado pelo painel no mesmo evento (ou globalmente, escopo 'global') —
equivalente ao `concurrency: group: automacao-a` que o GitHub Actions
garantia sozinho quando havia um único orquestrador.

Implementação simples (select, depois upsert) — existe uma janela de
corrida teórica entre as duas chamadas (dois cliques quase simultâneos
podiam, em tese, adquirir a trava ao mesmo tempo). Aceito conscientemente
pelo mesmo motivo que common.ensure_enum_value aceita uma janela parecida:
o volume de cliques humanos concorrentes no mesmo evento é baixíssimo, e
o pior caso (duas sincronizações do mesmo evento quase ao mesmo tempo) já
é tolerado hoje pelas escritas diff-only — não gera duplicidade, só uma
chamada extra ao Bitrix.
"""

from datetime import datetime, timedelta, timezone

from . import supabase_client

TABLE = "sync_locks"
TTL_MINUTES = 10


class SyncLockHeld(RuntimeError):
    """A trava já está em uso por outro processo e ainda não expirou."""


def acquire_lock(escopo: str, travado_por: str) -> None:
    existentes = supabase_client.select(TABLE, {"select": "*", "escopo": f"eq.{escopo}"})
    if existentes:
        travado_em = datetime.fromisoformat(existentes[0]["travado_em"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - travado_em < timedelta(minutes=TTL_MINUTES):
            raise SyncLockHeld(
                f"Escopo '{escopo}' já travado por '{existentes[0]['travado_por']}' desde {travado_em.isoformat()}."
            )
    row = {"escopo": escopo, "travado_em": datetime.now(timezone.utc).isoformat(), "travado_por": travado_por}
    supabase_client.upsert(TABLE, [row], on_conflict="escopo")


def release_lock(escopo: str) -> None:
    supabase_client.delete(TABLE, {"escopo": f"eq.{escopo}"})
