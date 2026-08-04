# Arquitetura

Este documento explica como as coisas funcionam por dentro. Se você só precisa operar o dia a dia (adicionar assessor, testar uma mudança, resolver um erro), o [`OPERACAO.md`](OPERACAO.md) é mais direto ao ponto. Aqui é pra quem vai mexer no código.

## Camadas do código (pós-refatoração)

O código deixou de ser um punhado de scripts soltos e passou a ter responsabilidade separada por camada:

- **`common/`** (era `common.py`, virou pacote): chamadas de API do Bitrix24 (`bitrix_client.py`) e da Sympla (`sympla_client.py`), com retry/backoff em falha transitória, mais normalização pura (`normalization.py`) e constantes/config vindas do `.env` (`constants.py`). Único ponto de acoplamento entre Automação A e Automação B — o `from common import (...)` da Automação B nunca muda.
- **`domain/`**: regras de negócio puras, sem chamada de rede — `stage_rules.py` (quando avançar estágio), `coupons.py` (cupom → assessor/origem), `matching.py` (cascata telefone→email→nome, testável com lookups falsos). Testadas por `pytest` sem precisar de credencial real.
- **`services/`**: orquestração. `lead_sync_service.py` é o motor de verdade (`sync_all_upcoming_events()`/`sync_one_event()`), usado tanto pelo Cron Job agendado quanto pelo painel. `coupon_service.py` e `config_service.py` resolvem cupom/campos consultando o Supabase, com fallback pro valor fixo se o banco cair.
- **`repositories/`**: acesso ao Supabase via REST (PostgREST), um wrapper fino por tabela — sem SDK adicional, mesmo espírito do `bitrix_client.py`.
- **`interface/`**: o painel administrativo (Dashboard/Eventos/Mapeamento/Cupons/Logs), um processo Flask **separado** da Automação B — nunca importa nem é importado por ela.
- **`automacao_a_inscricoes.py`**: virou um wrapper de CLI fino, só lê `TEST_EVENT_IDS` e chama `lead_sync_service.sync_all_upcoming_events()`.

## Tabelas no Supabase

- **`assessores_cupom`**: mapa cupom → assessor (ou cupom → origem de canal). Editável pela aba Cupons do painel. Fallback: `domain/coupons.py::_DEFAULT_ASSESSOR_POR_CUPOM`/`_DEFAULT_ORIGEM_POR_CUPOM_CANAL`.
- **`config_kv`**: códigos de campo/estágio do Bitrix (`FIELD_DATA_DO_EVENTO`, `FIELD_NOME_DO_EVENTO`, `FIELD_SYMPLA_EVENT_ID`, `FIELD_ORIGEM`, `FIELD_FILTRAR_EVENTO`, `STAGE_INSCRITO_PRO_EVENTO`). Editável pela aba Mapeamento. Fallback: valor do `.env` (`common/constants.py`). **`FIELD_PRESENTE_NO_EVENTO` não está aqui** — é da Automação B, que continua lendo direto do `.env`/secrets do próprio serviço dela.
- **`eventos_config`**: liga/desliga por evento (toggle Ativo/Inativo e "Remover" na aba Eventos) e os contadores/timestamp de sincronização que alimentam o Dashboard. Filtro fail-**aberto**: se essa tabela cair, todo evento é tratado como ativo (não trava a sincronização).
- **`participantes_processados`**: substitui o antigo `.cache/sympla_processed.json` — idempotência real, compartilhada entre o Cron Job e o painel. Fail-**fechado**: se não conseguir ler, o evento inteiro é pulado naquela rodada (nunca trata "não consegui ler" como "ninguém processado ainda").
- **`sync_locks`**: trava contra o painel e o Cron Job tentarem sincronizar o mesmo evento ao mesmo tempo.
- **`execucoes_log`**/**`execucoes_log_itens`**: histórico de execuções (1 linha por rodada completa) e de ações (1 linha por evento sincronizado) — alimentam Dashboard e a aba Logs.

## O formato real dos dados da Sympla

A documentação oficial da Sympla é incompleta em alguns pontos, e a gente descobriu o formato de verdade testando contra a API. Vale registrar pra ninguém precisar redescobrir:

**Telefone e CPF** vêm dentro de `custom_form`, como respostas do formulário de inscrição, não como campos fixos do participante. O texto da pergunta varia de evento pra evento ("Telefone", "WhatsApp/Telefone", "Celular"), por isso `extract_phone()` em `common.py` procura por palavras-chave no nome da pergunta em vez de um nome de campo fixo.

**Cupom de desconto** é a parte mais traiçoeira. Existem dois lugares onde ele pode aparecer:
- `participant.order_discount`, direto no registro do participante.
- `order.discount_code`, no registro do pedido (`/events/{id}/orders`), que precisa ser cruzado pelo `order_id` do participante.

`extract_discount_code()` tenta o primeiro e cai pro segundo se estiver vazio. E aqui mora a pegadinha: quando não tem desconto, a Sympla não deixa o campo vazio nem null, ela manda a string `"0"` (às vezes `"0.00"`). Em Python, `"0"` é uma string não vazia, então testar só `if valor:` engana e trata como se fosse um cupom de verdade. `_is_no_discount_value()` existe só pra pegar esse caso.

**Check-in** vem em `participant.checkin.check_in_date`. Se a chave existir com uma data, a pessoa fez check-in.

## Como um inscrito vira Lead (ou atualiza um existente)

A Automação A tenta achar um Lead já existente antes de criar um novo, numa cascata:

1. **Telefone** (`crm.duplicate.findbycomm`, tipo PHONE), o sinal mais confiável, porque o Bitrix já normaliza duplicidade por telefone.
2. **E-mail** (mesmo método, tipo EMAIL), só tentado se o telefone não achou nada.
3. **Nome**, último recurso. Em vez de baixar todos os Leads do portal (que já passou de 20 mil), filtra pelo Bitrix com `%NAME` contendo o nome do inscrito e confirma localmente com `normalize_name()` (ignora acento, maiúscula, espaçamento duplicado).

Se nenhum dos três achar nada e o inscrito tiver telefone, cria um Lead novo. Sem telefone e sem match, a automação desiste e só loga um aviso (não dá pra criar um Lead minimamente confiável sem telefone).

Quando a Sympla passar a coletar CPF no formulário (já vimos que alguns eventos já pedem), o lugar natural pra entrar na cascata é antes do telefone, como o identificador mais confiável de todos.

## Cupom vira responsável

Cada assessor tem seu próprio cupom (formato tipo `"100.00% - IARA"`). O mapa cupom → e-mail do assessor vem da tabela `assessores_cupom` no Supabase (editável pela aba Cupons do painel, sem precisar de deploy), resolvida por `services/coupon_service.py`. Se o Supabase estiver fora do ar, sem credencial configurada, ou a tabela vazia, cai pros dicts fixos em `domain/coupons.py` (`_DEFAULT_ASSESSOR_POR_CUPOM`/`_DEFAULT_ORIGEM_POR_CUPOM_CANAL`). O e-mail resolvido vira ID numérico via `resolve_user_id_by_email()` (que chama `user.get`, cacheado).

Isso só acontece na **criação** de um Lead novo. Se o inscrito já tinha um Lead (achado pela cascata acima), a automação nunca sobrescreve o responsável ou a origem dele.

Alguns cupons não são de um assessor específico, são de canal de aquisição (o exemplo que já apareceu é `MILETO`, tráfego pago). Esses ficam marcados como `tipo = 'canal'` na mesma tabela, e só marcam a Origem do Lead, sem atribuir responsável nenhum.

Cupom sem mapeamento não trava nada: o Lead é criado do mesmo jeito, com Origem "Inscrito Desconhecido" e um aviso no log, pra alguém notar que falta atualizar o mapa.

Pra adicionar assessor ou variação de cupom nova, o jeito mais simples é pela aba Cupons do painel — o passo a passo antigo (editar código) está no `OPERACAO.md` só como referência histórica.

## Dois modelos de estágio, e por que eles existem separados

`STAGES_SAFE_TO_ADVANCE` (`NEWLEAD`, `NEWFUP`) são os estágios iniciais do funil atual. Um Lead nesses estágios pode ser avançado automaticamente pra "Inscrito Pro Evento" quando bate uma inscrição.

`OLD_FUNNEL_STAGES` são os estágios do funil antigo, de antes da reformulação do pipeline (`NEW`, `IN_PROCESS`, `PROCESSED`, `UC_DQZKWD`, `UC_PFVCRN`, `UC_Z0M384`, `UC_VL3WIF`). Um Lead nesses estágios pode ganhar os campos de evento (data, nome, ID Sympla), mas o estágio dele nunca muda. A automação não promove ninguém de volta pro funil novo sozinha, isso é decisão de gente.

Tem uma pegadinha aqui: `UC_TJ9FPC` ("Reunião") não segue o padrão de nome dos estágios novos (não tem o prefixo `[NEW]`), mas é funil novo mesmo assim. Se o funil mudar de novo no futuro, vale conferir cada estágio na tela do Bitrix antes de simplesmente confiar no prefixo do nome.

**Nenhum desses dois modelos vai até "Pós Evento".** Esse estágio (e o que acontece nele — marcar presença) fica inteiramente fora deste repositório: é uma automação nativa do Bitrix (robô/regra de funil configurada na própria tela do Bitrix) que move o Lead pra lá, em algum momento depois do evento. É a ENTRADA nesse estágio que dispara o `/webhook/pos-evento` da Automação B (ver docstring de `automacao_b_presenca.py`), não o contrário — nenhum script daqui decide quando isso acontece. Na prática isso significa que um Lead pode passar horas ou dias em "Inscrito Pro Evento" sem o campo "Presente no Evento" nunca aparecer preenchido, e isso não é bug: é só que o robô do Bitrix ainda não moveu ele pra "Pós Evento".

## A tabela que evita reprocessar todo mundo

A cada execução, seria caro (e desnecessário) reprocessar todos os inscritos de todos os eventos de novo. A tabela `participantes_processados` (Supabase) guarda, por evento, quais IDs de participante já foram tratados com sucesso — substituiu o antigo arquivo `.cache/sympla_processed.json` (que só funcionava bem enquanto havia um único orquestrador rodando via GitHub Actions; com o painel também podendo disparar sincronização sob demanda, o estado precisa ser compartilhado entre os dois).

Um detalhe importante: só entra na tabela quem foi processado **com sucesso**. Se der erro no meio do caminho (permissão faltando, campo não configurado, instabilidade de rede), aquele inscrito fica de fora e é tentado de novo na próxima execução. Isso já evitou perder gente de verdade: teve uma fase em que um erro de permissão no webhook fazia a criação de Lead falhar silenciosamente, e sem essa proteção esses inscritos teriam sumido pra sempre.

A leitura de "quem já foi processado" é **fail-fechado**: se a tabela estiver inacessível, o evento inteiro é pulado naquela rodada (conta como erro, tenta de novo na próxima execução) — nunca trata "não consegui ler" como "ninguém processado ainda", ou o motor reprocessaria tudo a cada rodada até o Supabase voltar. Isso é diferente do fallback de cupom/mapeamento (que falha **aberto** pro valor fixo no código): perder o estado de idempotência é mais perigoso do que perder uma config, então aqui a escolha é parar em vez de arriscar.

Dois pontos de entrada usam essa tabela: o Cron Job agendado (`services/lead_sync_service.py::sync_all_upcoming_events()`) e o painel, quando alguém clica "Sincronizar agora"/"Forçar atualização de campos" num evento específico (`sync_one_event()`). Como agora são dois processos independentes que podem tocar o mesmo evento, a tabela `sync_locks` evita que os dois sincronizem o mesmo evento ao mesmo tempo.

## Peculiaridades da API do Bitrix que já morderam a gente

- `crm.lead.userfield.list` não devolve o rótulo do campo (`EDIT_FORM_LABEL`) na resposta, mesmo que você tenha setado ele na criação. Por isso os scripts de setup acham campo existente pelo `FIELD_NAME` (o código técnico), não pelo texto visível na tela.
- `crm.lead.userfield.update`, quando usado num campo tipo enumeration, **substitui a lista inteira** de opções em vez de fazer merge. Adicionar um valor novo sem apagar os que já existem exige reenviar todos os itens atuais (com o ID de cada um) mais os novos (sem ID).
- O webhook de entrada precisa do escopo `Usuários (user)`, além de `CRM (crm)`, pra conseguir chamar `user.get`. Sem isso, a resolução de responsável por e-mail falha com 401, mas só quando o cupom bate com um assessor mapeado, então o erro pode passar despercebido por um tempo se ninguém estiver de olho nos logs.
- Workflows agendados do GitHub Actions rodam bem mais espaçado do que o cron configurado sugere. Um `*/7 * * * *` na prática dispara a cada poucas horas, não a cada 7 minutos, porque o GitHub posterga execuções de baixa prioridade quando o sistema está sob carga. Isso é esperado, não é bug. Por isso o schedule foi reduzido pra `*/30 * * * *` (rede de segurança) e o disparo confiável de verdade passou a ser externo (cron-job.org chamando `workflow_dispatch` a cada 10min) — ver `.github/workflows/automacao_a.yml`. Rodar o motor num Render Cron Job (ou num endpoint HTTP no mesmo processo do painel) foi cogitado e descartado: o plano free do Render tem só 512MB de RAM, e `sync_all_upcoming_events()` rodando dentro do processo do painel chegou a derrubar o worker por OOM num teste real. Os runners do GitHub Actions têm bem mais RAM de sobra pra isso, de graça.
- `crm.lead.userfield.update` não devolve o ID do item recém-criado numa lista de enumeration — `common.ensure_enum_value()` precisa relistar o campo depois do update pra descobrir. Existe uma janela de corrida (dois runs criando o mesmo item novo ao mesmo tempo) que o bloco `concurrency` do workflow praticamente elimina; como defesa residual, `ensure_enum_value` converge pro item de menor ID se achar duplicata, e loga um warning em vez de tentar apagar sozinha.
