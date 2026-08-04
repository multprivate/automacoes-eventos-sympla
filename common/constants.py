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

# SPA nativa "Eventos Sympla" do Bitrix (Fase 4) — entityTypeId 1112,
# criada por um app terceiro (Zopu, já descontinuado) antes deste projeto.
# O prefixo numérico dos campos (36) é o `id` do tipo em crm.type.list, não
# o entityTypeId — os dois números são coisas diferentes, já confundiu
# gente por causa disso.
BITRIX_SPA_ENTITY_TYPE_ID = int(os.environ.get("BITRIX_SPA_ENTITY_TYPE_ID", "1112"))
FIELD_SPA_SYMPLA_EVENT_ID = os.environ.get("BITRIX_FIELD_SPA_SYMPLA_EVENT_ID", "ufCrm36_1785860529")
FIELD_SPA_TOTAL_INSCRITOS = os.environ.get("BITRIX_FIELD_SPA_TOTAL_INSCRITOS", "ufCrm36_1774557810585")
FIELD_SPA_TOTAL_PRESENTES = os.environ.get("BITRIX_FIELD_SPA_TOTAL_PRESENTES", "ufCrm36_1774557823941")
FIELD_SPA_TOTAL_FALTOSOS = os.environ.get("BITRIX_FIELD_SPA_TOTAL_FALTOSOS", "ufCrm36_1774557838417")
FIELD_SPA_ULTIMA_SINCRONIZACAO = os.environ.get("BITRIX_FIELD_SPA_ULTIMA_SINCRONIZACAO", "ufCrm36_1774557862742")
FIELD_SPA_NOME_EVENTO = os.environ.get("BITRIX_FIELD_SPA_NOME_EVENTO", "ufCrm36_1774557988935")

# Campo espelhado (mesmo nome) tanto em Lead quanto em Contact — aponta pro
# ID do item da SPA ao qual aquele Lead/Contact está vinculado.
FIELD_PARENT_ID_EVENTO_SPA = "PARENT_ID_1112"

ORIGEM_VALOR_FORMULARIO = "Formulario"                            # texto; o ID é resolvido em runtime via resolve_enum_id
ORIGEM_VALOR_INSCRITO_DESCONHECIDO = "Inscrito Desconhecido"      # idem — inscrito sem cupom (ou cupom não mapeado); reaproveita valor já existente no portal
ORIGEM_VALOR_CUPOM_DESCONTO = "Cupom de Desconto"                 # idem — inscrito com cupom de um assessor mapeado
ORIGEM_VALOR_TRAFEGO_PAGO = "Trafego Pago"                        # idem — cupom de canal (não de assessor), ex: "MILETO"
VALOR_PRESENTE = "Presente"             # idem
VALOR_NAO_PRESENTE = "Não Presente"     # idem
