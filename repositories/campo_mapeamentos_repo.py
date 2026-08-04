"""
Acesso à tabela `mapeamentos_campos` — mapeamentos extras de campo
definidos pelo usuário via aba Mapeamento (ver domain/campo_extra_mapeamento.py).
"""

from . import supabase_client

TABLE = "mapeamentos_campos"


def list_ativos() -> list[dict]:
    """Levanta supabase_client.SupabaseUnavailable ou
    requests.RequestException — quem chama (services/campo_mapeamento_service.py)
    decide cair pra "sem mapeamentos extras nesta rodada" (fail-aberto:
    perder um campo extra é bem menos grave que travar a sincronização)."""
    return supabase_client.select(TABLE, {"select": "*", "ativo": "eq.true"})


def create(origem_dado: str, bitrix_field_code: str, aplicar_em: str) -> dict:
    row = {"origem_dado": origem_dado, "bitrix_field_code": bitrix_field_code, "aplicar_em": aplicar_em}
    return supabase_client.insert(TABLE, row)


def delete(mapeamento_id: str) -> None:
    supabase_client.delete(TABLE, {"id": f"eq.{mapeamento_id}"})
