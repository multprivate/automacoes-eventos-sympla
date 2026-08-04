"""
Cascata de matching telefone -> e-mail -> nome: a DECISÃO de qual critério
tentar e em que ordem, isolada das chamadas reais ao Bitrix.

lookup_by_phone/lookup_by_email/lookup_by_name são callables injetados
(assinatura `str -> list[int]`) — em produção, automacao_a_inscricoes.py
passa as funções reais de common.bitrix_client; em teste, dá pra passar
stubs e verificar a cascata sem nenhuma chamada de rede.

Próximo degrau natural, quando a Sympla passar a coletar CPF: checar CPF
antes de telefone, é o identificador mais confiável.
"""

from typing import Callable

LookupFn = Callable[[str], list[int]]


def find_matching_lead_ids(
    phone_key: str,
    email: str,
    full_name: str,
    lookup_by_phone: LookupFn,
    lookup_by_email: LookupFn,
    lookup_by_name: LookupFn,
) -> tuple[list[int], str | None]:
    if phone_key:
        lead_ids = lookup_by_phone(phone_key)
        if lead_ids:
            return lead_ids, "telefone"

    if email:
        lead_ids = lookup_by_email(email)
        if lead_ids:
            return lead_ids, "email"

    lead_ids = lookup_by_name(full_name)
    return lead_ids, ("nome" if lead_ids else None)


def find_matching_contact_ids(
    phone_key: str,
    email: str,
    lookup_by_phone: LookupFn,
    lookup_by_email: LookupFn,
) -> tuple[list[int], str | None]:
    """Cascata telefone -> e-mail, SEM fallback por nome (diferente da
    cascata de Lead). Um Contato representa um cliente de verdade — um
    match por nome (sujeito a falso positivo, ex: dois "João Silva"
    diferentes) vincularia a inscrição de um estranho ao histórico de um
    cliente real, um erro bem mais caro do que o mesmo tipo de engano
    aconteceria com um Lead desconhecido."""
    if phone_key:
        contact_ids = lookup_by_phone(phone_key)
        if contact_ids:
            return contact_ids, "telefone"

    if email:
        contact_ids = lookup_by_email(email)
        if contact_ids:
            return contact_ids, "email"

    return [], None


def contact_needs_new_lead(open_lead_ids: list[int]) -> bool:
    """True se o Contato (cliente) não tem nenhum Lead aberto no funil
    agora — nesse caso, a inscrição no evento vira um Lead novo pra
    representar esse interesse. Isolado numa função (mesmo trivial) porque
    é uma regra de negócio nomeada, não um detalhe de implementação — se
    "aberto" precisar excluir estágios específicos (ex: convertido/perdido)
    no futuro, é aqui que essa definição muda."""
    return not open_lead_ids


def choose_primary_contact_id(contact_ids: list[int]) -> int:
    """Quando um inscrito bate com mais de um Contato (dado duplicado
    pré-existente no Bitrix, não causado pela automação — ex: mesmo e-mail
    cadastrado em dois Contatos), escolhe um só pra vincular, em vez de
    criar/vincular um Lead por Contato batido. O de ID mais baixo é
    normalmente o mais antigo/estabelecido — critério simples e
    determinístico, não uma mesclagem de verdade (isso fica pra uma tarefa
    separada, tratada com mais cuidado por envolver dado real de cliente)."""
    return min(contact_ids)
