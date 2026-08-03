-- Fase 3 da reestruturação: motor sob demanda (painel) + idempotência e
-- config de eventos no Postgres. Aditivo — não toca em assessores_cupom,
-- config_kv nem execucoes_log (já existentes, da branch feature/interface).
--
-- Rode este arquivo no SQL Editor do painel do Supabase (projeto
-- "multprivate's sympla + bitrix", referenciado por SUPABASE_URL no .env).

-- Liga/desliga por evento — Ativo/Inativo e "Remover" da aba Eventos.
-- ativo e removido_em são campos separados de propósito: o toggle é uma
-- pausa reversível de um clique, "Remover" é uma decisão mais forte (some
-- da lista padrão, mas nunca é DELETE físico — o log fino referencia
-- sympla_event_id, apagar quebraria esse histórico).
create table if not exists public.eventos_config (
    sympla_event_id text primary key,
    nome_evento text,
    data_evento date,
    ativo boolean not null default true,
    removido_em timestamptz,
    inscritos_count int not null default 0,
    presentes_count int not null default 0,
    ultimo_sync_em timestamptz,
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);

create or replace function public.set_updated_at()
returns trigger as $$
begin
    new.atualizado_em = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists eventos_config_set_updated_at on public.eventos_config;
create trigger eventos_config_set_updated_at
    before update on public.eventos_config
    for each row
    execute function public.set_updated_at();

-- Log fino (1 linha por ação) pra aba Logs — grão diferente de
-- execucoes_log (1 linha por execução completa, já existe, alimenta os
-- tiles agregados do Dashboard). Mantidos como tabelas separadas de
-- propósito: forçar os dois grãos num schema só exigiria reagregar toda
-- vez que o Dashboard carrega, ou perder o detalhe fino que a aba Logs
-- pede.
create table if not exists public.execucoes_log_itens (
    id bigserial primary key,
    execucao_id bigint references public.execucoes_log(id) on delete set null,
    acao text not null check (acao in (
        'EVENT_SYNCED', 'EVENT_UPDATED', 'EVENT_FIELDS_FORCED',
        'EVENT_REMOVED', 'EVENT_TOGGLED',
        'PARTICIPANT_CREATED', 'PARTICIPANT_UPDATED', 'PARTICIPANT_SKIPPED'
    )),
    entidade_tipo text not null check (entidade_tipo in ('evento', 'participante')),
    entidade_ref text,
    sympla_event_id text,
    status text not null check (status in ('ok', 'error')),
    duracao_ms int,
    erro text,
    detalhes jsonb,
    criado_em timestamptz not null default now()
);

create index if not exists execucoes_log_itens_criado_em_idx
    on public.execucoes_log_itens (criado_em desc);
create index if not exists execucoes_log_itens_sympla_event_id_idx
    on public.execucoes_log_itens (sympla_event_id);
create index if not exists execucoes_log_itens_entidade_tipo_idx
    on public.execucoes_log_itens (entidade_tipo);

-- Idempotência — substitui .cache/sympla_processed.json. Mesma invariante
-- de hoje: só entra linha depois que o participante foi processado com
-- sucesso.
create table if not exists public.participantes_processados (
    sympla_event_id text not null,
    participant_id text not null,
    processado_em timestamptz not null default now(),
    primary key (sympla_event_id, participant_id)
);

-- Trava contra corrida entre o Cron Job agendado e um "Sincronizar agora"
-- disparado pelo painel no mesmo evento — equivalente ao
-- `concurrency: group: automacao-a` que o GitHub Actions garantia sozinho,
-- agora explícito porque há dois pontos de entrada pro mesmo motor.
create table if not exists public.sync_locks (
    escopo text primary key,
    travado_em timestamptz not null default now(),
    travado_por text not null
);
