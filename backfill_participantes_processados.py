"""
Script pontual (roda uma vez, antes do corte pra idempotência em Postgres):
lê o cache local .cache/sympla_processed.json e faz upsert em
participantes_processados no Supabase, pra evitar a rajada de
reprocessamento que aconteceria se o corte fosse feito "a seco".

Nota: o cache real usado em produção vive dentro do GitHub Actions
(restaurado via actions/cache a cada run) — o arquivo local pode estar
alguns dias desatualizado em relação a ele. Isso não é um problema sério:
como as escritas no Bitrix são sempre diff-only, os poucos inscritos que
ficarem de fora deste backfill só geram uma atualização extra (idempotente)
na primeira execução pós-corte, não duplicidade nem perda de dado.

Uso:
    python backfill_participantes_processados.py
"""

import json
import logging

from repositories.processed_repo import mark_processed_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("backfill_participantes_processados")

CACHE_PATH = ".cache/sympla_processed.json"


def main() -> None:
    with open(CACHE_PATH) as f:
        raw = json.load(f)

    total = 0
    for event_id, participant_ids in raw.items():
        ids = set(participant_ids)
        mark_processed_batch(event_id, ids)
        total += len(ids)
        log.info("%s: %d participante(s) marcado(s) como já processado(s).", event_id, len(ids))

    log.info("Backfill concluído: %d evento(s), %d participante(s) no total.", len(raw), total)


if __name__ == "__main__":
    main()
