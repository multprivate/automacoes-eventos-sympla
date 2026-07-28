# Arquitetura

Este documento explica como as coisas funcionam por dentro. Se você só precisa operar o dia a dia (adicionar assessor, testar uma mudança, resolver um erro), o [`OPERACAO.md`](OPERACAO.md) é mais direto ao ponto. Aqui é pra quem vai mexer no código.

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

Cada assessor tem seu próprio cupom (formato tipo `"100.00% - IARA"`). O mapa `ASSESSOR_POR_CUPOM` em `automacao_a_inscricoes.py` traduz o texto do cupom pro e-mail do assessor no Bitrix, e dali pro ID numérico via `resolve_user_id_by_email()` (que chama `user.get`, cacheado).

Isso só acontece na **criação** de um Lead novo. Se o inscrito já tinha um Lead (achado pela cascata acima), a automação nunca sobrescreve o responsável ou a origem dele.

Alguns cupons não são de um assessor específico, são de canal de aquisição (o exemplo que já apareceu é `MILETO`, tráfego pago). Esses ficam num mapa separado, `ORIGEM_POR_CUPOM_CANAL`, que só marca a Origem do Lead, sem atribuir responsável nenhum.

Cupom sem mapeamento não trava nada: o Lead é criado do mesmo jeito, com Origem "Inscrito Desconhecido" e um aviso no log, pra alguém notar que falta atualizar o mapa.

Pra adicionar assessor ou variação de cupom nova, o passo a passo está no `OPERACAO.md`.

## Dois modelos de estágio, e por que eles existem separados

`STAGES_SAFE_TO_ADVANCE` (`NEWLEAD`, `NEWFUP`) são os estágios iniciais do funil atual. Um Lead nesses estágios pode ser avançado automaticamente pra "Inscrito Pro Evento" quando bate uma inscrição.

`OLD_FUNNEL_STAGES` são os estágios do funil antigo, de antes da reformulação do pipeline (`NEW`, `IN_PROCESS`, `PROCESSED`, `UC_DQZKWD`, `UC_PFVCRN`, `UC_Z0M384`, `UC_VL3WIF`). Um Lead nesses estágios pode ganhar os campos de evento (data, nome, ID Sympla), mas o estágio dele nunca muda. A automação não promove ninguém de volta pro funil novo sozinha, isso é decisão de gente.

Tem uma pegadinha aqui: `UC_TJ9FPC` ("Reunião") não segue o padrão de nome dos estágios novos (não tem o prefixo `[NEW]`), mas é funil novo mesmo assim. Se o funil mudar de novo no futuro, vale conferir cada estágio na tela do Bitrix antes de simplesmente confiar no prefixo do nome.

## O cache que evita reprocessar todo mundo

A cada execução, seria caro (e desnecessário) reprocessar todos os inscritos de todos os eventos de novo. O cache guarda, por evento, quais IDs de participante já foram tratados com sucesso.

Local, é um arquivo `.cache/sympla_processed.json`. No GitHub Actions, é o cache nativo (`actions/cache`), restaurado no início da execução e salvo no final, com uma chave única por execução (`sympla-processed-${{ github.run_id }}`) e `restore-keys` pra sempre pegar a versão mais recente salva antes.

Um detalhe importante: só entra no cache quem foi processado **com sucesso**. Se der erro no meio do caminho (permissão faltando, campo não configurado, instabilidade de rede), aquele inscrito fica de fora do cache e é tentado de novo na próxima execução. Isso já evitou perder gente de verdade: teve uma fase em que um erro de permissão no webhook fazia a criação de Lead falhar silenciosamente, e sem essa proteção esses inscritos teriam sumido pra sempre.

## Peculiaridades da API do Bitrix que já morderam a gente

- `crm.lead.userfield.list` não devolve o rótulo do campo (`EDIT_FORM_LABEL`) na resposta, mesmo que você tenha setado ele na criação. Por isso os scripts de setup acham campo existente pelo `FIELD_NAME` (o código técnico), não pelo texto visível na tela.
- `crm.lead.userfield.update`, quando usado num campo tipo enumeration, **substitui a lista inteira** de opções em vez de fazer merge. Adicionar um valor novo sem apagar os que já existem exige reenviar todos os itens atuais (com o ID de cada um) mais os novos (sem ID).
- O webhook de entrada precisa do escopo `Usuários (user)`, além de `CRM (crm)`, pra conseguir chamar `user.get`. Sem isso, a resolução de responsável por e-mail falha com 401, mas só quando o cupom bate com um assessor mapeado, então o erro pode passar despercebido por um tempo se ninguém estiver de olho nos logs.
- Workflows agendados do GitHub Actions rodam bem mais espaçado do que o cron configurado sugere. Um `*/7 * * * *` na prática dispara a cada poucas horas, não a cada 7 minutos, porque o GitHub posterga execuções de baixa prioridade quando o sistema está sob carga. Isso é esperado, não é bug.
