-- Adiciona um novo tipo de ação ao log fino, pra registrar quando um
-- inscrito bate com mais de um Contato no Bitrix (dado duplicado
-- pré-existente, não causado pela automação) — fica registrado pra
-- revisão/mesclagem manual, em vez de silenciosamente criar um Lead por
-- Contato duplicado.

alter table public.execucoes_log_itens drop constraint if exists execucoes_log_itens_acao_check;
alter table public.execucoes_log_itens add constraint execucoes_log_itens_acao_check check (acao in (
    'EVENT_SYNCED', 'EVENT_UPDATED', 'EVENT_FIELDS_FORCED',
    'EVENT_REMOVED', 'EVENT_TOGGLED',
    'PARTICIPANT_CREATED', 'PARTICIPANT_UPDATED', 'PARTICIPANT_SKIPPED',
    'CONTATO_DUPLICADO'
));
