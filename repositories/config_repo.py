"""
Acesso à tabela `config_kv` (chave -> valor) — generaliza os
BITRIX_FIELD_*/BITRIX_STAGE_* pra fora do .env, editável pela aba
Mapeamento do painel sem precisar de deploy.
"""

from . import supabase_client

TABLE = "config_kv"


def get_all() -> dict[str, str]:
    """Levanta supabase_client.SupabaseUnavailable ou
    requests.RequestException — quem chama (services/config_service.py)
    decide cair pro valor fixo em common/constants.py."""
    rows = supabase_client.select(TABLE, {"select": "chave,valor,descricao"})
    return {row["chave"]: row["valor"] for row in rows if row.get("valor")}


def upsert(chave: str, valor: str, descricao: str | None = None) -> dict:
    row = {"chave": chave, "valor": valor}
    if descricao is not None:
        row["descricao"] = descricao
    return supabase_client.upsert(TABLE, [row], on_conflict="chave")[0]
