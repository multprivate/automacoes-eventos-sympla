"""
Cupom -> assessor responsável (só usado na CRIAÇÃO de Lead novo — nunca
sobrescreve responsável/origem de um Lead já existente que a automação
encontrar por telefone/e-mail/nome).

Função pura: recebe os mapas prontos (cupom->e-mail, cupom->origem de
canal) e só decide — quem monta esses mapas (Supabase, com fallback pros
_DEFAULT_* abaixo) é services/coupon_service.py.

_DEFAULT_ASSESSOR_POR_CUPOM/_DEFAULT_ORIGEM_POR_CUPOM_CANAL espelham a aba
"Mapa_Assessores" do Extrator.gs (Google Apps Script) já validada em
produção — chave já normalizada (trim+upper). Em produção, o mapa de
verdade vem da tabela `assessores_cupom` no Supabase (editável sem
precisar de deploy); estes dicts só entram se o Supabase estiver fora do
ar, sem credencial configurada, ou com a tabela vazia.
"""

import logging

from common import (
    ORIGEM_VALOR_CUPOM_DESCONTO,
    ORIGEM_VALOR_INSCRITO_DESCONHECIDO,
    ORIGEM_VALOR_TRAFEGO_PAGO,
    normalize_cupom,
)

log = logging.getLogger("domain.coupons")

_DEFAULT_ASSESSOR_POR_CUPOM = {
    "100.00% - BRUNA": "bruna.tassia@multprivate.seg.br",
    "100.00% - EDUARDO": "eduardo.forte@multprivate.seg.br",
    "100.00% - IARA": "iara.araujo@multprivate.seg.br",
    "100.00% - JULIANA": "juliana.cintra@multprivate.com.br",
    "100.00% - MARCOS": "marcos.mourao@multprivate.com.br",
    "100.00% - RICARDO": "joao.nogueira@multprivate.seg.br",
    "100.00% - RODRIGO": "rodrigo.onias@multprivate.seg.br",
    "100.00% - STEFANO": "stefano.silva@multprivate.com.br",
    "100.00% - STHEFANY": "sthefany.muniz@multprivate.com.br",
    "100.00% - MUNIZ": "sthefany.muniz@multprivate.com.br",
    "100.00% - RAQUEL": "celedonio@multprivate.seg.br",
    "100.00% - THAIS": "thais.oliveira@multprivate.com.br",
    "100% - JOAO": "joao.nogueira@multprivate.seg.br",
}

# Cupons que não são de um assessor específico, e sim de um canal de
# aquisição — só marcam a Origem do Lead pra rastreio, sem responsável.
_DEFAULT_ORIGEM_POR_CUPOM_CANAL = {
    "100.00% - MILETO": ORIGEM_VALOR_TRAFEGO_PAGO,
}


def resolve_assessor_and_origem(cupom: str, assessor_por_cupom: dict[str, str], origem_por_cupom_canal: dict[str, str]) -> tuple[str | None, str]:
    if not cupom:
        return None, ORIGEM_VALOR_INSCRITO_DESCONHECIDO

    key = normalize_cupom(cupom)

    email = assessor_por_cupom.get(key)
    if email:
        return email, ORIGEM_VALOR_CUPOM_DESCONTO

    origem_canal = origem_por_cupom_canal.get(key)
    if origem_canal:
        return None, origem_canal

    log.warning("Cupom '%s' não mapeado em nenhum assessor nem canal — Lead fica sem responsável específico.", cupom)
    return None, ORIGEM_VALOR_INSCRITO_DESCONHECIDO
