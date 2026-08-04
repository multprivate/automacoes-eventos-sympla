"""
Cliente REST (PostgREST) genérico pro Supabase — sem SDK adicional, mesmo
espírito de common/bitrix_client.py: um wrapper HTTP fino por cima de
`requests`.

Credenciais lidas em cada chamada (não no import do módulo): assim, se
SUPABASE_URL/SUPABASE_SERVICE_KEY ainda não estiverem configurados (ex:
segredo não adicionado no GitHub Actions ainda), quem importa este módulo
não quebra — só quem de fato TENTA usar uma tabela sente o efeito, e
decide (via CouponsRepoUnavailable e afins) se cai pro fallback.
"""

import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("repositories.supabase_client")


class SupabaseUnavailable(RuntimeError):
    """SUPABASE_URL/SUPABASE_SERVICE_KEY não configurados no ambiente."""


def _base_url_and_headers() -> tuple[str, dict[str, str]]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise SupabaseUnavailable("SUPABASE_URL/SUPABASE_SERVICE_KEY não configurados no ambiente.")
    return url, {"apikey": key, "Authorization": f"Bearer {key}"}


def select(table: str, params: dict | None = None) -> list[dict]:
    """Levanta SupabaseUnavailable se não configurado, ou
    requests.RequestException/HTTPError em falha de rede/API — quem chama
    decide o que fazer (normalmente: cair pro fallback hardcoded)."""
    url, headers = _base_url_and_headers()
    resp = requests.get(f"{url}/rest/v1/{table}", headers=headers, params=params or {"select": "*"}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def insert(table: str, row: dict) -> dict:
    """Insere uma linha nova (sem upsert/merge) e propaga erro — pra
    tabelas com PK gerada automaticamente (ex: uuid default), onde não
    existe uma coluna natural pra resolver conflito."""
    url, headers = _base_url_and_headers()
    headers = {**headers, "Content-Type": "application/json", "Prefer": "return=representation"}
    resp = requests.post(f"{url}/rest/v1/{table}", headers=headers, json=row, timeout=10)
    resp.raise_for_status()
    return resp.json()[0]


def upsert(table: str, rows: list[dict], on_conflict: str) -> list[dict]:
    """Insere ou atualiza (merge pela coluna em on_conflict). Propaga erro
    — diferente de select(), uma falha aqui precisa ser visível pra quem
    salvou algo pelo painel achar que deu certo sem ter dado.

    Todo dict em rows precisa ter o MESMO conjunto de chaves (None pra
    coluna que não se aplica) — o PostgREST rejeita upsert em lote com
    objetos de formato diferente entre si (erro PGRST102)."""
    url, headers = _base_url_and_headers()
    headers = {**headers, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=representation"}
    resp = requests.post(f"{url}/rest/v1/{table}", headers=headers, params={"on_conflict": on_conflict}, json=rows, timeout=10)
    resp.raise_for_status()
    return resp.json()


def delete(table: str, filters: dict) -> None:
    """Remove linhas que batem com filters (ex: {"cupom": "eq.MILETO"}).
    Propaga erro, mesmo motivo de upsert()."""
    url, headers = _base_url_and_headers()
    resp = requests.delete(f"{url}/rest/v1/{table}", headers=headers, params=filters, timeout=10)
    resp.raise_for_status()


def insert_best_effort(table: str, row: dict) -> None:
    """Insere uma linha sem propagar erro — pra dado de observabilidade
    (ex: log de execução) onde perder o registro não deve derrubar a
    automação de verdade."""
    try:
        url, headers = _base_url_and_headers()
    except SupabaseUnavailable:
        return
    headers = {**headers, "Content-Type": "application/json", "Prefer": "return=minimal"}
    try:
        resp = requests.post(f"{url}/rest/v1/{table}", headers=headers, json=row, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Falha ao gravar em '%s' no Supabase (melhor esforço, seguindo em frente): %s", table, exc)
