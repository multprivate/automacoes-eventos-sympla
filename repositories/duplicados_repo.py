"""
Acesso à tabela `duplicados_candidatos` — pares de Lead que a varredura
periódica de telefone (services/duplicidade_service.py) achou com o
mesmo número, pendentes de revisão humana na aba "Verificação de
Duplicados" do painel.
"""

from datetime import datetime, timezone

from . import supabase_client

TABLE = "duplicados_candidatos"


def get_pendentes() -> list[dict]:
    """Levanta supabase_client.SupabaseUnavailable ou
    requests.RequestException — quem chama decide o que fazer (a aba do
    painel mostra lista vazia com aviso; a varredura só não teria como
    checar duplicata já conhecida e arriscaria reinserir, então propaga)."""
    return supabase_client.select(TABLE, {"select": "*", "status": "eq.pendente", "order": "criado_em.desc"})


def existe_par(lead_id_a: int, lead_id_b: int) -> bool:
    rows = supabase_client.select(
        TABLE, {"select": "id", "lead_id_a": f"eq.{lead_id_a}", "lead_id_b": f"eq.{lead_id_b}"}
    )
    return bool(rows)


def insert_candidato(lead_id_a: int, lead_id_b: int, nome_a: str, nome_b: str, telefone_a: str, telefone_b: str) -> dict:
    row = {
        "lead_id_a": lead_id_a,
        "lead_id_b": lead_id_b,
        "nome_a": nome_a,
        "nome_b": nome_b,
        "telefone_a": telefone_a,
        "telefone_b": telefone_b,
    }
    return supabase_client.insert(TABLE, row)


def get_by_id(candidato_id: str) -> dict | None:
    rows = supabase_client.select(TABLE, {"select": "*", "id": f"eq.{candidato_id}"})
    return rows[0] if rows else None


def set_status(candidato_id: str, status: str) -> None:
    supabase_client.update(
        TABLE, {"id": f"eq.{candidato_id}"}, {"status": status, "resolvido_em": datetime.now(timezone.utc).isoformat()}
    )
