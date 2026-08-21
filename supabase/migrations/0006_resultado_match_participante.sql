-- Guarda o RESULTADO do match de cada inscrito (era cliente? por qual
-- sinal? qual card no Bitrix?) junto da marca de idempotência que já
-- existe em participantes_processados — é atributo do mesmo fato
-- ("inscrito P do evento E foi processado com sucesso"), escrito no
-- mesmo instante, pelo mesmo upsert em lote de
-- services/lead_sync_service.py::process_event.
--
-- Aditivo e retro-compatível: todas as colunas são anuláveis e NÃO há
-- backfill possível (o resultado do match nunca foi capturado
-- historicamente). Linha antiga = is_cliente NULL = "não verificado" na
-- aba Inscritos, até alguém reprocessar aquele inscrito.
--
-- processado_em (já existente) continua sendo a PRIMEIRA vez que o
-- inscrito foi visto — mark_processed_batch nunca manda essa coluna no
-- payload, então o ON CONFLICT do PostgREST não a sobrescreve. É o
-- "Data encontrado" da tela. verificado_em é o par dela: a ÚLTIMA vez
-- que o match foi recalculado (muda a cada "Reprocessar").
--
-- Sem CHECK constraint em match_method de propósito: mark_processed_batch
-- roda dentro de um try/except em process_event (falha aqui não pode
-- derrubar a sincronização de verdade, que já rodou no Bitrix) — uma
-- violação de constraint faria o LOTE INTEIRO falhar, perdendo a marca
-- de idempotência de todo mundo naquela rodada, não só de quem teria o
-- valor inválido. Valores documentados via comment on column em vez de
-- travados.

alter table public.participantes_processados
    add column if not exists is_cliente boolean,
    add column if not exists match_method text,
    add column if not exists bitrix_contact_id bigint,
    add column if not exists bitrix_lead_id bigint,
    add column if not exists contact_ids_duplicados jsonb,
    add column if not exists verificado_em timestamptz;

comment on column public.participantes_processados.is_cliente is
    'true = bateu com um Contato do Bitrix (cliente); false = não bateu (prospect); null = processado antes desta migração, resultado desconhecido.';
comment on column public.participantes_processados.match_method is
    'Sinal que fechou o match: cpf | telefone | email | nome (nome só existe na cascata de Lead). null = nenhum critério bateu, ou linha legada.';
comment on column public.participantes_processados.bitrix_contact_id is
    'Contato usado no branch cliente (o de menor ID, se houve duplicata). null no branch prospect.';
comment on column public.participantes_processados.bitrix_lead_id is
    'Lead do ESTE evento criado ou atualizado nesta rodada. null quando o inscrito não gerou/tocou nenhum Lead (ex: sem telefone e sem match).';
comment on column public.participantes_processados.contact_ids_duplicados is
    'Lista completa de Contatos batidos quando foram mais de um (duplicata pré-existente no Bitrix, não criada pela automação). Espelha o detalhes.contact_ids do log CONTATO_DUPLICADO. null = sem duplicata.';
comment on column public.participantes_processados.verificado_em is
    'Última vez que o match foi recalculado (sincronização normal ou botão "Reprocessar" na aba Inscritos) — diferente de processado_em, que é sempre a primeira vez.';
