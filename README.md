# automacao-crm-sympla

Sincroniza inscrições em eventos da Sympla com o Bitrix24 CRM: casa cada inscrito com um Lead (ou cria um novo), preenche os dados do evento, e — quando o evento já passou — marca presença e move o Lead pra "Pós Evento". Tudo orquestrado por um único motor (`services/lead_sync_service.py`, chamado de "Automação A"), usado tanto pelo Cron Job agendado quanto pelo painel administrativo.

## Como os dados fluem

```mermaid
flowchart LR
    subgraph Sympla
        S1[Eventos]
        S2[Participantes]
        S3[Pedidos / cupons]
    end

    subgraph GitHub[GitHub Actions - cron]
        A[Motor de sincronização]
    end

    subgraph Painel[Painel administrativo]
        P[interface_app.py]
    end

    subgraph Bitrix24
        L[Leads]
    end

    S1 --> A
    S2 --> A
    S3 --> A
    A -->|cria/atualiza, inclusive presença + Pós Evento| L
    P -->|"Sincronizar agora" / "Forçar campos"| A
```

O motor tenta achar um Lead já existente antes de criar um novo (telefone → e-mail → nome). Quando o inscrito bate com um Contato (cliente) já cadastrado, vincula em vez de duplicar. O botão **"Forçar atualização de campos"**, na aba Eventos do painel, além de reenviar os campos do evento, também preenche "Presente no evento" e move o Lead pra "Pós Evento" quando o evento já aconteceu — substitui o que antes era um robô nativo do Bitrix + um segundo serviço web ("Automação B", aposentada).

## Os arquivos

| Arquivo/pasta | O que faz |
|---|---|
| `common/` | Chamadas às APIs da Sympla e do Bitrix24 (com retry em falha transitória), normalização pura (telefone/e-mail/nome/CPF), e constantes/config vindas do `.env`. |
| `domain/` | Regras de negócio puras, sem chamada de rede: quando avançar estágio, cascata de matching, cupom → assessor/origem, mesclagem de duplicados. Testável sem credencial real. |
| `services/` | Orquestração — `lead_sync_service.py` é o motor de verdade; `config_service.py`/`coupon_service.py` resolvem config/cupom via Supabase com fallback fixo; `duplicidade_service.py` cuida da varredura de duplicados. |
| `repositories/` | Acesso ao Supabase via REST (PostgREST), um wrapper fino por tabela. |
| `interface/` | O painel administrativo (Dashboard/Eventos/Mapeamento/Cupons/Verificação de Duplicados/Logs), Blueprints Flask. |
| `automacao_a_inscricoes.py` | Wrapper de CLI fino sobre `lead_sync_service.sync_all_upcoming_events()` — o que o GitHub Actions chama. |
| `interface_app.py` | Ponto de entrada do painel administrativo. |
| `verificar_duplicados.py` | Wrapper de CLI fino sobre `duplicidade_service.detectar_duplicados_por_telefone()` — varredura diária de Leads duplicados. |
| `setup_custom_fields.py` | Garante que os campos customizados e estágios que o motor precisa existem no Bitrix. Roda uma vez, ou de novo quando algo muda. |
| `preview_novos_leads.py` | Mostra o que a sincronização faria em cada inscrito, sem escrever nada no Bitrix. |
| `relatorio_participantes.py` | Script pontual pra gerar um CSV com todos os participantes de todos os eventos, cruzando com o Bitrix. Não faz parte do ciclo normal. |
| `.github/workflows/automacao_a.yml` | Agenda o motor de sincronização no GitHub Actions. |
| `.github/workflows/verificar_duplicados.yml` | Agenda a varredura de duplicados (diária). |
| `railpack.json` | Comando de start do painel administrativo no Railway. |
| `render.yaml` | Blueprint do Render (alternativa de hospedagem) pro painel administrativo. |

Detalhes de como cada peça funciona por dentro (formato dos dados da Sympla, lógica de matching, cache, peculiaridades da API do Bitrix) estão em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md). Passo a passo de operação do dia a dia (adicionar assessor, testar com segurança, resolver erro comum) está em [`docs/OPERACAO.md`](docs/OPERACAO.md).

## Rodando local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# preenche o .env com os valores reais (token Sympla, webhook Bitrix, códigos de campo, Supabase)

python setup_custom_fields.py     # garante que os campos/estágios existem no Bitrix
python preview_novos_leads.py     # mostra o que aconteceria, sem escrever nada
python automacao_a_inscricoes.py  # roda de verdade
```

Pra rodar o painel administrativo localmente:

```bash
flask --app interface_app run --port 5002
```

## Deploy

**Motor de sincronização** roda no GitHub Actions (`.github/workflows/automacao_a.yml`), disparado por um cron externo (cron-job.org) chamando a API `workflow_dispatch` — o `schedule:` nativo do GitHub Actions é só rede de segurança, ele sozinho dispara com atraso sob carga. Precisa desses secrets configurados no repositório (Settings → Secrets and variables → Actions):

- `SYMPLA_TOKEN`
- `BITRIX_WEBHOOK_URL`
- `BITRIX_STAGE_INSCRITO_PRO_EVENTO`
- `BITRIX_FIELD_DATA_DO_EVENTO`
- `BITRIX_FIELD_NOME_DO_EVENTO`
- `BITRIX_FIELD_SYMPLA_EVENT_ID`
- `BITRIX_FIELD_ORIGEM`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`

A idempotência (quem já foi processado) é guardada na tabela `participantes_processados` do Supabase — não em cache do GitHub Actions, ela é compartilhada com o painel, que também pode disparar sincronização sob demanda.

A varredura de duplicados (`.github/workflows/verificar_duplicados.yml`) roda diariamente pelo mesmo mecanismo, precisando só de `SYMPLA_TOKEN`, `BITRIX_WEBHOOK_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`.

**Painel administrativo** roda como um serviço web separado (`interface_app.py`). Hoje hospedado no Railway (usa `railpack.json` pra definir o comando de start, já que o builder não detecta sozinho qual dos scripts é o app), com `render.yaml` mantido como alternativa/histórico caso volte pro Render. Precisa dessas env vars:

- `SYMPLA_TOKEN`
- `BITRIX_WEBHOOK_URL`
- `BITRIX_STAGE_INSCRITO_PRO_EVENTO`
- `BITRIX_FIELD_DATA_DO_EVENTO`
- `BITRIX_FIELD_NOME_DO_EVENTO`
- `BITRIX_FIELD_SYMPLA_EVENT_ID`
- `BITRIX_FIELD_ORIGEM`
- `BITRIX_FIELD_FILTRAR_EVENTO`
- `BITRIX_FIELD_PRESENTE_NO_EVENTO`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `ADMIN_PASSWORD`
- `FLASK_SECRET_KEY`

Hospedagens free-tier costumam dormir depois de um tempo sem tráfego — um serviço externo (cron-job.org ou similar) batendo no endpoint `/health` periodicamente mantém o painel acordado.

O webhook de entrada do Bitrix precisa das permissões `CRM (crm)` e `Usuários (user)` (essa segunda é usada pra descobrir o ID do assessor responsável a partir do e-mail).
