"""
Cascata de matching CPF -> telefone -> e-mail -> nome: a DECISÃO de qual
critério tentar e em que ordem, isolada das chamadas reais ao Bitrix.

lookup_by_cpf/lookup_by_phone/lookup_by_email/lookup_by_name são
callables injetados (assinatura `str -> list[int]`) — em produção,
services/lead_sync_service.py passa as funções reais de
common.bitrix_client; em teste, dá pra passar stubs e verificar a cascata
sem nenhuma chamada de rede.

CPF é o critério mais forte (único por pessoa desde que o Sympla passou a
coletar CPF obrigatório no formulário de inscrição) — checado primeiro,
sem a defesa de confirmação por nome que telefone/e-mail têm (ver
find_matching_lead_ids). Continua opcional: inscrições antigas ou eventos
sem a pergunta de CPF simplesmente não têm esse critério disponível
(`normalize_cpf` retorna "") e a cascata cai pros critérios de sempre.
"""

from typing import Callable

from common import normalize_name

LookupFn = Callable[[str], list[int]]
NameLookupFn = Callable[[int], str]


def names_are_compatible(name_a: str, name_b: str) -> bool:
    """Compara dois nomes por inclusão de palavras inteiras (não
    igualdade exata, não substring bruta) — true se todas as palavras do
    nome mais curto aparecem, cada uma inteira, no nome mais longo.

    Igualdade exata é rígida demais: "Kelly Sabina" (como a pessoa
    digitou no Sympla) e "KELLY SABINA PASSOS SANTOS" (nome completo já
    cadastrado no Bitrix) são a MESMA pessoa, mas normalize_name(a) ==
    normalize_name(b) dá False — rejeitaria um match legítimo e criaria
    um Lead duplicado. Substring bruta também não serve ("ana" apareceria
    dentro de "mariana", nomes de pessoas diferentes) — por isso a
    comparação é por palavra inteira, não caractere a caractere."""
    palavras_a = set(normalize_name(name_a).split())
    palavras_b = set(normalize_name(name_b).split())
    if not palavras_a or not palavras_b:
        return False
    menor, maior = (palavras_a, palavras_b) if len(palavras_a) <= len(palavras_b) else (palavras_b, palavras_a)
    return menor.issubset(maior)


def find_matching_lead_ids(
    cpf: str,
    phone_key: str,
    email: str,
    full_name: str,
    lookup_by_cpf: LookupFn,
    lookup_by_phone: LookupFn,
    lookup_by_email: LookupFn,
    lookup_by_name: LookupFn,
    get_lead_name: NameLookupFn,
) -> tuple[list[int], str | None]:
    """get_lead_name resolve o NAME de um candidato achado por telefone ou
    e-mail, pra confirmar que é a mesma pessoa antes de aceitar o match —
    necessário porque o Sympla pode reaproveitar o telefone/e-mail de
    quem comprou/organizou pra vários inscritos reais diferentes (ex: um
    casal dividindo o mesmo celular, cupom de cortesia em grupo gerado
    por um assessor). A confirmação é por names_are_compatible (palavra
    inteira, não igualdade exata) — "Kelly Sabina" no Sympla confirma
    contra "KELLY SABINA PASSOS SANTOS" no Bitrix. Se os nomes forem
    incompatíveis, o match é rejeitado nesse passo e a cascata continua
    pro próximo critério. Sem nome no inscrito, não há sinal pra
    rejeitar, então mantém o comportamento antigo (aceita sem confirmar).

    CPF (primeiro passo) NÃO passa por essa confirmação: é único por
    pessoa por definição, exigir nome bater em cima disso só criaria
    falso-negativo (nome legal diferente do nome usado no Sympla) sem
    ganho de segurança real."""
    if cpf:
        lead_ids = lookup_by_cpf(cpf)
        if lead_ids:
            return lead_ids, "cpf"

    def _confirmados(candidate_ids: list[int]) -> list[int]:
        if not candidate_ids or not full_name:
            return candidate_ids
        return [cid for cid in candidate_ids if names_are_compatible(full_name, get_lead_name(cid))]

    if phone_key:
        confirmed_ids = _confirmados(lookup_by_phone(phone_key))
        if confirmed_ids:
            return confirmed_ids, "telefone"

    if email:
        confirmed_ids = _confirmados(lookup_by_email(email))
        if confirmed_ids:
            return confirmed_ids, "email"

    lead_ids = lookup_by_name(full_name)
    return lead_ids, ("nome" if lead_ids else None)


def find_matching_contact_ids(
    cpf: str,
    phone_key: str,
    email: str,
    lookup_by_cpf: LookupFn,
    lookup_by_phone: LookupFn,
    lookup_by_email: LookupFn,
) -> tuple[list[int], str | None]:
    """Cascata CPF -> telefone -> e-mail, SEM fallback por nome (diferente
    da cascata de Lead). Um Contato representa um cliente de verdade — um
    match por nome (sujeito a falso positivo, ex: dois "João Silva"
    diferentes) vincularia a inscrição de um estranho ao histórico de um
    cliente real, um erro bem mais caro do que o mesmo tipo de engano
    aconteceria com um Lead desconhecido. CPF não tem esse risco (é único
    por pessoa), por isso pode ser o primeiro critério com segurança."""
    if cpf:
        contact_ids = lookup_by_cpf(cpf)
        if contact_ids:
            return contact_ids, "cpf"

    if phone_key:
        contact_ids = lookup_by_phone(phone_key)
        if contact_ids:
            return contact_ids, "telefone"

    if email:
        contact_ids = lookup_by_email(email)
        if contact_ids:
            return contact_ids, "email"

    return [], None


def contact_needs_new_event_lead(existing_event_lead_ids: list[int]) -> bool:
    """True se o Contato (cliente) ainda não tem um Lead vinculado a ESTE
    evento — nesse caso, a inscrição vira um Lead novo em "Inscrito Pro
    Evento", mesmo que o Contato já tenha outro Lead aberto em outro
    estágio (ex: negociação em andamento). Um Lead de negociação paralela
    nunca deve impedir nem ser afetado pela inscrição no evento — regra de
    negócio confirmada: todo cliente que se inscreve precisa aparecer como
    card próprio em Inscrito Pro Evento. `existing_event_lead_ids` já vem
    filtrado por evento (vínculo com o item da SPA), não é "qualquer Lead
    aberto do Contato"."""
    return not existing_event_lead_ids


def choose_primary_lead_id(
    lead_a_id: int,
    lead_b_id: int,
    tem_vinculo_spa_a: bool,
    tem_vinculo_spa_b: bool,
    tem_email_a: bool,
    tem_email_b: bool,
    activities_a: int,
    activities_b: int,
) -> tuple[int, int]:
    """Decide qual dos dois Leads de um par duplicado (services/
    duplicidade_service.py::executar_merge) vira o principal (sobrevive) e
    qual vira o secundário (é apagado depois de preservar o que tiver de
    valor). Critério, em ordem de prioridade: quem já está vinculado a um
    item da SPA de evento > quem tem e-mail cadastrado > quem tem mais
    Activities (histórico de interação) > menor ID (mais antigo). Retorna
    (id_principal, id_secundario)."""
    candidatos = [
        (lead_a_id, tem_vinculo_spa_a, tem_email_a, activities_a),
        (lead_b_id, tem_vinculo_spa_b, tem_email_b, activities_b),
    ]
    principal = max(candidatos, key=lambda c: (c[1], c[2], c[3], -c[0]))
    secundario = lead_b_id if principal[0] == lead_a_id else lead_a_id
    return principal[0], secundario


def choose_primary_contact_id(contact_ids: list[int]) -> int:
    """Quando um inscrito bate com mais de um Contato (dado duplicado
    pré-existente no Bitrix, não causado pela automação — ex: mesmo e-mail
    cadastrado em dois Contatos), escolhe um só pra vincular, em vez de
    criar/vincular um Lead por Contato batido. O de ID mais baixo é
    normalmente o mais antigo/estabelecido — critério simples e
    determinístico, não uma mesclagem de verdade (isso fica pra uma tarefa
    separada, tratada com mais cuidado por envolver dado real de cliente)."""
    return min(contact_ids)
