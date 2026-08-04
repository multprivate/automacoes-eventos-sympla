"""
Acesso à tabela `assessores_cupom` no Supabase — o mapa cupom -> assessor
responsável (ou cupom -> origem de canal). Tabela já existia no projeto
Supabase real (de uma tentativa anterior de painel admin, nunca mergeada
no código) com dado já seedado — reaproveitada aqui como está, sem
renomear colunas nem criar uma tabela nova.

Schema (supabase/migrations, projeto "multprivate's sympla + bitrix"):
    cupom          text primary key   -- ex: "100.00% - BRUNA"
    tipo           text               -- 'assessor' | 'canal'
    email_assessor text nullable      -- obrigatório quando tipo='assessor'
    origem_canal   text nullable      -- obrigatório quando tipo='canal'
    atualizado_em  timestamptz
"""

from . import supabase_client

TABLE = "assessores_cupom"


def list_coupons() -> list[dict]:
    """Levanta supabase_client.SupabaseUnavailable ou
    requests.RequestException — quem chama (services/coupon_service.py)
    decide cair pro fallback fixo no código."""
    return supabase_client.select(TABLE, {"select": "*"})


def upsert_coupon(cupom: str, tipo: str, email_assessor: str | None, origem_canal: str | None) -> dict:
    row = {
        "cupom": cupom,
        "tipo": tipo,
        "email_assessor": email_assessor if tipo == "assessor" else None,
        "origem_canal": origem_canal if tipo == "canal" else None,
    }
    return supabase_client.upsert(TABLE, [row], on_conflict="cupom")[0]


def delete_coupon(cupom: str) -> None:
    supabase_client.delete(TABLE, {"cupom": f"eq.{cupom}"})
