"""
Configuração e constantes compartilhadas entre Automação A e Automação B:
credenciais das APIs, códigos de campo do Bitrix24 e os textos fixos usados
nos campos de lista (enumeration).
"""

import os

from dotenv import load_dotenv

load_dotenv()

SYMPLA_TOKEN = os.environ["SYMPLA_TOKEN"]
BITRIX_WEBHOOK_URL = os.environ["BITRIX_WEBHOOK_URL"].rstrip("/")

SYMPLA_BASE = "https://api.sympla.com.br/public/v1.5.1"

STAGE_INSCRITO_PRO_EVENTO = os.environ.get("BITRIX_STAGE_INSCRITO_PRO_EVENTO", "UC_2CK7JY")
STAGES_SAFE_TO_ADVANCE = {"NEWLEAD", "NEWFUP"}

# Estágios do funil antigo (pré-reformulação do pipeline) — um Lead nesses
# estágios pode ganhar os campos de evento (Data/Nome/ID Sympla) quando
# bate uma inscrição nova, pra dar visibilidade, mas o STATUS_ID nunca
# muda: a automação não "promove" ninguém de volta pro funil novo sozinha.
# Note que UC_TJ9FPC ("Reunião") NÃO entra aqui apesar de não ter o
# prefixo [NEW]: é do funil novo.
OLD_FUNNEL_STAGES = {"NEW", "IN_PROCESS", "PROCESSED", "UC_DQZKWD", "UC_PFVCRN", "UC_Z0M384", "UC_VL3WIF"}

FIELD_DATA_DO_EVENTO = os.environ.get("BITRIX_FIELD_DATA_DO_EVENTO", "")
FIELD_NOME_DO_EVENTO = os.environ.get("BITRIX_FIELD_NOME_DO_EVENTO", "")
FIELD_SYMPLA_EVENT_ID = os.environ.get("BITRIX_FIELD_SYMPLA_EVENT_ID", "")
FIELD_ORIGEM = os.environ.get("BITRIX_FIELD_ORIGEM", "")
FIELD_PRESENTE_NO_EVENTO = os.environ.get("BITRIX_FIELD_PRESENTE_NO_EVENTO", "")
FIELD_FILTRAR_EVENTO = os.environ.get("BITRIX_FIELD_FILTRAR_EVENTO", "")

ORIGEM_VALOR_FORMULARIO = "Formulario"                            # texto; o ID é resolvido em runtime via resolve_enum_id
ORIGEM_VALOR_INSCRITO_DESCONHECIDO = "Inscrito Desconhecido"      # idem — inscrito sem cupom (ou cupom não mapeado); reaproveita valor já existente no portal
ORIGEM_VALOR_CUPOM_DESCONTO = "Cupom de Desconto"                 # idem — inscrito com cupom de um assessor mapeado
ORIGEM_VALOR_TRAFEGO_PAGO = "Trafego Pago"                        # idem — cupom de canal (não de assessor), ex: "MILETO"
VALOR_PRESENTE = "Presente"             # idem
VALOR_NAO_PRESENTE = "Não Presente"     # idem
