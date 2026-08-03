"""
Retry com backoff exponencial pras chamadas HTTP de bitrix_client e
sympla_client. Isolado aqui porque é puramente uma preocupação de
transporte — não devia vazar pra quem chama bitrix_call/get_all_events/etc,
que continuam vendo só "funcionou ou levantou uma exceção".

Retenta em falha de conexão/timeout e em status 429/5xx (transitórios por
natureza). Não retenta 4xx (exceto 429): erro de request não se resolve
tentando de novo.
"""

import logging
import time

import requests

log = logging.getLogger("common.http")

MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 0.5
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    last_exc: requests.exceptions.RequestException | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.request(method, url, **kwargs)
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt == MAX_ATTEMPTS:
                raise
            _wait_and_log(method, url, attempt, f"falha de conexão: {exc}")
            continue

        if resp.status_code in _RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
            _wait_and_log(method, url, attempt, f"status {resp.status_code}")
            continue
        return resp

    raise last_exc  # pragma: no cover — inalcançável, o raise acima já cobre o último attempt


def _wait_and_log(method: str, url: str, attempt: int, reason: str) -> None:
    wait = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
    log.warning(
        "%s %s (tentativa %d/%d) — %s — tentando de novo em %.1fs",
        method, url, attempt, MAX_ATTEMPTS, reason, wait,
    )
    time.sleep(wait)
