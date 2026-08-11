-- Candidatos a Lead duplicado achados pela varredura periódica de
-- telefone (services/duplicidade_service.py) — fica pendente até um
-- humano decidir, pela aba "Verificação de Duplicados" do painel, se
-- mescla ou ignora. lead_id_a é sempre o menor dos dois IDs (ordenação
-- normalizada), pra o UNIQUE não deixar a mesma dupla entrar duas vezes
-- entre rodadas diferentes da varredura.

create table public.duplicados_candidatos (
    id bigint generated always as identity primary key,
    lead_id_a bigint not null,
    lead_id_b bigint not null,
    nome_a text,
    nome_b text,
    telefone_a text,
    telefone_b text,
    status text not null default 'pendente' check (status in ('pendente', 'mesclado', 'ignorado')),
    criado_em timestamptz not null default now(),
    resolvido_em timestamptz,
    unique (lead_id_a, lead_id_b)
);

create index duplicados_candidatos_status_idx on public.duplicados_candidatos (status);
