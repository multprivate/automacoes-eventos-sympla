"""
Automação A: wrapper de CLI fino sobre services/lead_sync_service.py — lê
TEST_EVENT_IDS do ambiente e chama sync_all_upcoming_events(). Toda a
lógica (matching, cupom, avanço de estágio, cache de idempotência) vive
no serviço; este módulo só existe como ponto de entrada de linha de
comando (pensado pra rodar via Cron Job/GitHub Actions).

Uso:
    python automacao_a_inscricoes.py
"""

import logging
import os

from services.lead_sync_service import sync_all_upcoming_events

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("automacao_a_inscricoes")


def main() -> None:
    test_event_ids = {e.strip() for e in os.environ.get("TEST_EVENT_IDS", "").split(",") if e.strip()}
    summary = sync_all_upcoming_events(test_event_ids=test_event_ids or None)
    log.info("Execução concluída: %s", summary)


if __name__ == "__main__":
    main()
