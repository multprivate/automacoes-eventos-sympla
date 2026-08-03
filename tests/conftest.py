"""
common/constants.py exige SYMPLA_TOKEN e BITRIX_WEBHOOK_URL no ambiente
assim que é importado (mesmo comportamento de sempre, herdado do antigo
common.py). Os testes deste pacote só exercitam lógica pura de domain/ e
common/normalization.py — nenhuma chamada de rede de verdade acontece —
então valores fake bastam pra permitir o import sem precisar de
credenciais reais. setdefault() não sobrescreve um .env real já carregado.
"""

import os

os.environ.setdefault("SYMPLA_TOKEN", "test-token")
os.environ.setdefault("BITRIX_WEBHOOK_URL", "https://example.bitrix24.com.br/rest/1/test/")
