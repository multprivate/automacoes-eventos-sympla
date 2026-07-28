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
| `TEST_EVENT_IDS` | Não | A | Lista de `event_id` (separados por vírgula) pra restringir a Automação A só a esses eventos. Deixe vazio em produção. |

Se um campo opcional ficar vazio, a automação simplesmente não mexe naquele campo do Lead (não quebra, só ignora).

## Adicionando um assessor ou variação de cupom

O mapa fica em `automacao_a_inscricoes.py`, na constante `ASSESSOR_POR_CUPOM`. A chave é o texto do cupom em maiúsculas (o mesmo formato que a Sympla manda, tipo `"100.00% - IARA"`), o valor é o e-mail do assessor no Bitrix.

1. Confirma o e-mail certo do assessor no Bitrix.
2. Adiciona a linha no dicionário.
3. Se for uma porcentagem diferente da que já existe pro mesmo assessor (por exemplo já tem `"100.00% - IARA"` e agora precisa de `"70% - IARA"`), adiciona como uma chave nova, não troca a existente.
4. Testa com `preview_novos_leads.py` antes de confiar (veja a seção de teste abaixo).
5. Commita e dá push (o próprio usuário faz o push, não peça pro Claude fazer isso).

Cupom de canal, sem assessor específico (o exemplo hoje é tráfego pago), vai no dicionário `ORIGEM_POR_CUPOM_CANAL`, logo abaixo.

## Testando uma mudança sem afetar leads reais

Antes de confiar em qualquer mudança na lógica de matching, criação de Lead ou mapa de assessores, dois passos:

**1. `preview_novos_leads.py`** mostra o que a automação faria em cada participante de cada evento, sem escrever nada no Bitrix. Roda contra os eventos de verdade, então é bom pra ver se o comportamento geral faz sentido, mas não cria dado nenhum.

```bash
python preview_novos_leads.py
```

**2. `TEST_EVENT_IDS`**, no `.env` local, restringe a Automação A (a de verdade, com escrita) a um evento específico. O jeito mais seguro de validar uma mudança de ponta a ponta é criar um evento de teste na Sympla (precisa estar publicado, rascunho não aparece pra API), cadastrar 1 ou 2 inscritos de teste nele, pegar o `event_id` interno (não o número que aparece no painel: use `resolve_event_id()` em `common.py` pra converter) e rodar assim:

```bash
# no .env local
TEST_EVENT_IDS=s35acb4

python automacao_a_inscricoes.py
```

Isso cria/atualiza Leads de verdade, mas só pros participantes desse evento. Depois de validar, limpa o `TEST_EVENT_IDS` do `.env` local (não precisa mexer em nada na produção, essa variável nunca deve ir pro GitHub Secrets).

## Checando a saúde da produção

A Automação A roda no GitHub Actions. Pra ver o histórico de execuções:

```bash
gh run list --workflow=automacao_a.yml --limit 15
```

E pra ver o log de uma execução específica:

```bash
gh run view <run_id> --log
```

Um log saudável mostra, pra cada evento, quantos inscritos novos apareceram e o que foi feito com cada um (`Lead X atualizado`, `Novo lead X criado`, `Nenhum inscrito novo`). Se aparecer `[ERROR]` ou `Falha ao processar`, vale investigar: o inscrito não foi perdido (o cache só marca sucesso), mas alguma coisa está bloqueando o processamento dele, e vai continuar tentando até resolver.

## Erros comuns e o que fazer

**`401 Client Error: Unauthorized` em `user.get`**
O webhook de entrada do Bitrix não tem a permissão de usuários. Na tela do webhook (Aplicações → Webhooks → o webhook de entrada), em "Atribuir permissões", adiciona `Usuários (user)` ao lado de `CRM (crm)` e salva.

**`Item 'X' não encontrado na lista do campo Y`**
O valor não existe como opção no campo enumeration do Bitrix (Origem, Presente no evento). Roda `python setup_custom_fields.py`, ele confere os campos e adiciona os valores que faltarem sem apagar os que já existem.

**Campo não bate / dado indo pro lugar errado**
Confere se o código do campo no `.env` (ou no secret do GitHub) é o mesmo que está configurado de verdade no Bitrix. Códigos de campo mudam quando alguém recria ou renomeia o campo pela tela, e isso já aconteceu antes.

**`400 Bad Request` em `crm.lead.userfield.add`**
Provavelmente já existe um campo com esse `FIELD_NAME`, e o script tentou criar de novo. Acontece quando o campo foi criado manualmente com um código fora do padrão que os scripts esperam. Confere na tela de Campos Personalizados do Bitrix se não ficou um campo duplicado.

## Automação B no Render

O plano free do Render dorme depois de um tempo sem tráfego (efeito colateral do free tier, não é bug nosso). Por isso tem um serviço externo de ping (cron-job.org ou parecido) batendo em `/health` a cada 10 minutos, só pra manter o serviço acordado. Se a Automação B começar a demorar muito pra responder ou a regra de automação do Bitrix começar a dar timeout, o primeiro lugar pra olhar é se esse ping externo ainda está ativo.

Deploy é automático: qualquer push na branch conectada ao Render dispara um novo deploy.
