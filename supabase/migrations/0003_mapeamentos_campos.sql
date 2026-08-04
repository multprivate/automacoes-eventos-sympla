-- Mapeamentos extras de campo: permite vincular, pela aba Mapeamento do
-- painel, um dado que o motor já sabe extrair de um participante (cupom,
-- telefone, nome completo, e-mail) a um campo qualquer do Bitrix — sem
-- precisar de ajuste de código a cada campo novo.
--
-- Não é mapeamento arbitrário de qualquer coisa: origem_dado é restrito,
-- na aplicação, à lista fechada em domain/campo_extra_mapeamento.py
-- (ORIGENS_DISPONIVEIS) — só o valor de bitrix_field_code é livre.

create table if not exists public.mapeamentos_campos (
    id uuid primary key default gen_random_uuid(),
    origem_dado text not null,
    bitrix_field_code text not null,
    aplicar_em text not null check (aplicar_em in ('novo', 'todos')),
    ativo boolean not null default true,
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);

create index if not exists mapeamentos_campos_ativo_idx on public.mapeamentos_campos (ativo) where ativo;

drop trigger if exists mapeamentos_campos_set_updated_at on public.mapeamentos_campos;
create trigger mapeamentos_campos_set_updated_at
    before update on public.mapeamentos_campos
    for each row
    execute function public.set_updated_at();
