# Operação

Guia pro dia a dia: o que fazer quando precisa mudar alguma coisa, como testar sem medo, e o que checar quando algo dá errado. Pra entender como o código funciona por dentro, veja [`ARQUITETURA.md`](ARQUITETURA.md).

## Variáveis de ambiente

| Variável | Obrigatória? | Usada em | Pra que serve |
|---|---|---|---|
| `SYMPLA_TOKEN` | Sim | A, B | Token da API da Sympla (`s_token`). |
| `BITRIX_WEBHOOK_URL` | Sim | A, B | URL do webhook de entrada do Bitrix, sem o nome do método no final. |
| `BITRIX_STAGE_INSCRITO_PRO_EVENTO` | Não (tem default) | A | Código do estágio "Inscrito Pro Evento" no funil de Leads. |
| `BITRIX_FIELD_DATA_DO_EVENTO` | Não | A | Código (`UF_CRM_...`) do campo customizado "Data do evento". |
| `BITRIX_FIELD_NOME_DO_EVENTO` | Não | A | Código do campo "Nome do evento". |
| `BITRIX_FIELD_SYMPLA_EVENT_ID` | Não | A, B | Código do campo com o ID interno do evento Sympla. |
| `BITRIX_FIELD_ORIGEM` | Não | A | Código do campo "Origem". |
| `BITRIX_FIELD_PRESENTE_NO_EVENTO` | Não | B | Código do campo "Presente no evento". |
| `BITRIX_FIELD_FILTRAR_EVENTO` | Não | A | Código do campo "Filtrar Evento" (lista, um item por evento — `"DD/MM/AA - Nome do Evento"`). Aparece como checkbox de múltipla seleção na aba de Filtros da listagem de Leads. |
| `TEST_EVENT_IDS` | Não | A | Lista de `event_id` (separados por vírgula) pra restringir a Automação A só a esses eventos. Deixe vazio em produção. |
| `SUPABASE_URL` | Não* | A, painel | URL do projeto Supabase. Sem ela, cupons/mapeamento caem pro fallback fixo no código, e o painel não funciona. |
| `SUPABASE_SERVICE_KEY` | Não* | A, painel | Chave de serviço do Supabase (acesso via REST/PostgREST). |
| `ADMIN_PASSWORD` | Sim (painel) | painel | Senha única de acesso ao painel administrativo. |
| `FLASK_SECRET_KEY` | Sim (painel) | painel | Assina o cookie de sessão do painel — gere um valor aleatório (`python3 -c "import secrets; print(secrets.token_hex(32))"`) e use o MESMO valor em todos os workers/deploys, senão o login não se mantém. |

\* Automação A funciona sem `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` (cai pro fallback fixo), mas o painel administrativo não funciona sem eles.

Se um campo opcional ficar vazio, a automação simplesmente não mexe naquele campo do Lead (não quebra, só ignora).

## Adicionando um assessor ou variação de cupom

Pelo painel (recomendado): aba **Cupons**, formulário "+ Novo cupom" — não precisa de deploy nem de editar código.

1. Confirma o e-mail certo do assessor no Bitrix.
2. Preenche cupom (mesmo formato que a Sympla manda, tipo `"100.00% - IARA"`), tipo "Assessor", e o e-mail.
3. Se for uma porcentagem diferente da que já existe pro mesmo assessor (por exemplo já tem `"100.00% - IARA"` e agora precisa de `"70% - IARA"`), cadastra como um cupom novo, não edita o existente.
4. Testa com `preview_novos_leads.py` antes de confiar (veja a seção de teste abaixo) — ele já lê o cupom do Supabase.

Cupom de canal, sem assessor específico (o exemplo hoje é tráfego pago), usa tipo "Canal de aquisição" no mesmo formulário.

Se o Supabase estiver fora do ar (raro), o mapa cai pros dicts fixos em `domain/coupons.py` (`_DEFAULT_ASSESSOR_POR_CUPOM`/`_DEFAULT_ORIGEM_POR_CUPOM_CANAL`) — editar esses dicts é o caminho de emergência, não o normal.

## Testando uma mudança sem afetar leads reais

Antes de confiar em qualquer mudança na lógica de matching, criação de Lead ou mapa de assessores, dois passos:

**1. `preview_novos_leads.py`** mostra o que a automação faria em cada participante de cada evento, sem escrever nada no Bitrix. Roda contra os eventos de verdade, então é bom pra ver se o comportamento geral faz sentido, mas não cria dado nenhum.

```bash
python preview_novos_leads.py
```

**2. `TEST_EVENT_IDS`**, no `.env` local, restringe a Automação A (a de verdade, com escrita) a um evento específico. O jeito mais seguro de validar uma mudança de ponta a ponta é criar um evento de teste na Sympla (precisa estar publicado, rascunho não aparece pra API), cadastrar 1 ou 2 inscritos de teste nele, pegar o `event_id` interno (não o número que aparece no painel do organizador Sympla: use `resolve_event_id()`, de `common`, pra converter) e rodar assim:

```bash
# no .env local
TEST_EVENT_IDS=s35acb4

python automacao_a_inscricoes.py
```

Isso cria/atualiza Leads de verdade, mas só pros participantes desse evento. Depois de validar, limpa o `TEST_EVENT_IDS` do `.env` local (não precisa mexer em nada na produção, essa variável nunca deve ir pro GitHub Secrets).

## O painel administrativo

Um Flask separado (`interface_app.py`, blueprints em `interface/`), rodando como serviço próprio no Render (`sympla-dashboard` no `render.yaml`) — nunca dentro do processo da Automação B. Login por senha única (`ADMIN_PASSWORD`).

- **Dashboard**: visão geral (eventos futuros/sincronizados, última execução).
- **Eventos**: lista de eventos com contadores, e os botões "Sincronizar agora" (só participantes novos), "Forçar atualização de campos" (reenvia os 4 campos de evento mesmo já iguais, sem forçar estágio), "Remover"/toggle Ativo-Inativo (pausa/exclui o evento da sincronização automática, sem apagar histórico).
- **Mapeamento**: edita `config_kv` (códigos de campo/estágio do Bitrix).
- **Cupons**: edita `assessores_cupom`.
- **Logs**: histórico fino de sincronizações (`execucoes_log_itens`), com duração e erro por evento.

Rodar local: `flask --app interface_app run --port 5002`.

## Checando a saúde da produção

**Pelo painel** (mais direto): aba Logs mostra sucesso/erro por evento sincronizado, e o Dashboard mostra a última execução.

**Pelo GitHub Actions** (enquanto o Cron Job do Render não substituiu o schedule — ver `docs/ARQUITETURA.md`): pra ver o histórico de execuções:

```bash
gh run list --workflow=automacao_a.yml --limit 15
```

E pra ver o log de uma execução específica:

```bash
gh run view <run_id> --log
```

Um log saudável mostra, pra cada evento, quantos inscritos novos apareceram e o que foi feito com cada um (`Lead X atualizado`, `Novo lead X criado`, `Nenhum inscrito novo`). Se aparecer `[ERROR]` ou `Falha ao processar`, vale investigar: o inscrito não foi perdido (a tabela de idempotência só marca sucesso), mas alguma coisa está bloqueando o processamento dele, e vai continuar tentando até resolver.

## Erros comuns e o que fazer

**`401 Client Error: Unauthorized` em `user.get`**
O webhook de entrada do Bitrix não tem a permissão de usuários. Na tela do webhook (Aplicações → Webhooks → o webhook de entrada), em "Atribuir permissões", adiciona `Usuários (user)` ao lado de `CRM (crm)` e salva.

**`Item 'X' não encontrado na lista do campo Y`**
O valor não existe como opção no campo enumeration do Bitrix (Origem, Presente no evento). Roda `python setup_custom_fields.py`, ele confere os campos e adiciona os valores que faltarem sem apagar os que já existem. (Filtrar Evento não dá esse erro — ele cria o item sozinho em runtime via `ensure_enum_value`; se der erro é porque o CAMPO em si ainda não existe, aí sim precisa rodar `setup_custom_fields.py` primeiro.)

**Campo não bate / dado indo pro lugar errado**
Confere se o código do campo no `.env` (ou no secret do GitHub) é o mesmo que está configurado de verdade no Bitrix. Códigos de campo mudam quando alguém recria ou renomeia o campo pela tela, e isso já aconteceu antes.

**`400 Bad Request` em `crm.lead.userfield.add`**
Provavelmente já existe um campo com esse `FIELD_NAME`, e o script tentou criar de novo. Acontece quando o campo foi criado manualmente com um código fora do padrão que os scripts esperam. Confere na tela de Campos Personalizados do Bitrix se não ficou um campo duplicado.

## Serviços no Render

O plano free do Render dorme depois de um tempo sem tráfego (efeito colateral do free tier, não é bug nosso). Os dois serviços web (`automacao-b-presenca` e `sympla-dashboard`) têm cada um seu próprio `/health` (público, sem login, só confirma que o processo está de pé) — e cada um precisa do seu próprio ping externo (cron-job.org ou parecido) batendo nele a cada 10 minutos pra não dormir. São dois jobs de cron separados, um por serviço; manter um dos dois vivo não mantém o outro acordado.

Se a Automação B começar a demorar muito pra responder ou a regra de automação do Bitrix começar a dar timeout, o primeiro lugar pra olhar é se o ping externo dela ainda está ativo. Mesma lógica pro painel: se o Dashboard/Logs demorar ~30-50s pra carregar na primeira visita do dia, é o cold start do free tier — confere se o ping em `/health` do `sympla-dashboard` está configurado e rodando.

Deploy é automático: qualquer push na branch conectada ao Render dispara um novo deploy.
