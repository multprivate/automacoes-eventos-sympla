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
| `services/` | Orquestração — `lead_sync_service.py` é o motor de verdade; `config_service.py`/`coupon_service.py` resolvem config/cupom via Supabase com fallback fixo; `duplicidade_service.py` cuida da varredura de duplicados; `campo_convidado_service.py` mantém as opções do campo "Cliente convidado para". |
| `repositories/` | Acesso ao Supabase via REST (PostgREST), um wrapper fino por tabela. |
| `interface/` | O painel administrativo (Dashboard/Eventos/Mapeamento/Cupons/Verificação de Duplicados/Logs), Blueprints Flask. |
| `scripts/` | Pontos de entrada de linha de comando, rodados com `python -m scripts.<nome>` (ver abaixo). |
| `interface_app.py` | Ponto de entrada do painel administrativo (`gunicorn interface_app:app`). |
| `supabase/migrations/` | Migrations SQL do painel, aplicadas em ordem numérica. A `0001` (tabelas base) não está versionada aqui — foi aplicada direto no Supabase. |
| `tests/` | Testes `pytest` (`pip install -r requirements-dev.txt`). |
| `.github/workflows/` | Agendamentos no GitHub Actions: sincronização (`automacao_a.yml`), varredura de duplicados (`verificar_duplicados.yml`, diária) e lista de eventos do campo "Cliente convidado para" (`sincronizar_lista_convidados.yml`, diária). |
| `railpack.json` | Comando de start do painel administrativo no Railway. |

Conteúdo de `scripts/`:

| Script | O que faz |
|---|---|
| `automacao_a_inscricoes` | Wrapper fino sobre `lead_sync_service.sync_all_upcoming_events()` — o que o GitHub Actions chama. |
| `verificar_duplicados` | Wrapper fino sobre `duplicidade_service.detectar_duplicados_por_telefone()`. |
| `sincronizar_lista_convidados` | Wrapper fino sobre `campo_convidado_service.sincronizar_opcoes_evento()`. |
| `setup_custom_fields` | Garante que os campos customizados e estágios que o motor precisa existem no Bitrix. Roda uma vez, ou de novo quando algo muda. |
| `preview_novos_leads` | Mostra o que a sincronização faria em cada inscrito, sem escrever nada no Bitrix. |

Detalhes de como cada peça funciona por dentro (formato dos dados da Sympla, lógica de matching, cache, peculiaridades da API do Bitrix) estão em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md). Passo a passo de operação do dia a dia (adicionar assessor, testar com segurança, resolver erro comum) está em [`docs/OPERACAO.md`](docs/OPERACAO.md).

## Rodando local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# preenche o .env com os valores reais (token Sympla, webhook Bitrix, códigos de campo, Supabase)

python -m scripts.setup_custom_fields     # garante que os campos/estágios existem no Bitrix
python -m scripts.preview_novos_leads     # mostra o que aconteceria, sem escrever nada
python -m scripts.automacao_a_inscricoes  # roda de verdade
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

A varredura de duplicados (`verificar_duplicados.yml`) roda diariamente, precisando só de `SYMPLA_TOKEN`, `BITRIX_WEBHOOK_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`. A sincronização da lista de eventos (`sincronizar_lista_convidados.yml`) também é diária e precisa só de `SYMPLA_TOKEN` e `BITRIX_WEBHOOK_URL`.

**Painel administrativo** roda como um serviço web separado (`interface_app.py`). Hoje hospedado no Railway (usa `railpack.json` pra definir o comando de start, já que o builder não detecta sozinho qual dos scripts é o app). Precisa dessas env vars:

- `SYMPLA_TOKEN`
- `BITRIX_WEBHOOK_URL`
- `BITRIX_STAGE_INSCRITO_PRO_EVENTO`
- `BITRIX_FIELD_DATA_DO_EVENTO`
- `BITRIX_FIELD_NOME_DO_EVENTO`
- `BITRIX_FIELD_SYMPLA_EVENT_ID`
- `BITRIX_FIELD_ORIGEM`
- `BITRIX_FIELD_FILTRAR_EVENTO`
- `BITRIX_FIELD_PRESENTE_NO_EVENTO`
- `BITRIX_STAGE_POS_EVENTO`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `ADMIN_PASSWORD`
- `FLASK_SECRET_KEY`

Hospedagens free-tier costumam dormir depois de um tempo sem tráfego — um serviço externo (cron-job.org ou similar) batendo no endpoint `/health` periodicamente mantém o painel acordado.

O webhook de entrada do Bitrix precisa das permissões `CRM (crm)` e `Usuários (user)` (essa segunda é usada pra descobrir o ID do assessor responsável a partir do e-mail).
