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

from common import normalize_name

LookupFn = Callable[[str], list[int]]
NameLookupFn = Callable[[int], str]


def find_matching_lead_ids(
    phone_key: str,
    email: str,
    full_name: str,
    lookup_by_phone: LookupFn,
    lookup_by_email: LookupFn,
    lookup_by_name: LookupFn,
    get_lead_name: NameLookupFn,
) -> tuple[list[int], str | None]:
    """get_lead_name resolve o NAME de um candidato achado por e-mail, pra
    confirmar que é a mesma pessoa antes de aceitar o match — necessário
    porque o Sympla pode reaproveitar o e-mail de quem comprou/organizou
    pra vários inscritos reais diferentes (ex: cupom de cortesia gerado
    por um assessor pra vários convidados). Se o nome não bater, o match
    por e-mail é rejeitado e a cascata cai pro passo de busca por nome —
    mesma defesa que esse passo já faz sozinho. Sem nome no inscrito, não
    há sinal pra rejeitar, então mantém o comportamento antigo (aceita)."""
    if phone_key:
        lead_ids = lookup_by_phone(phone_key)
        if lead_ids:
            return lead_ids, "telefone"

    if email:
        candidate_ids = lookup_by_email(email)
        if candidate_ids:
            key = normalize_name(full_name)
            confirmed_ids = (
                [cid for cid in candidate_ids if normalize_name(get_lead_name(cid)) == key]
                if key
                else candidate_ids
            )
            if confirmed_ids:
                return confirmed_ids, "email"

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
