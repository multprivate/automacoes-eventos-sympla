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
