from common import (
    ORIGEM_VALOR_CUPOM_DESCONTO,
    ORIGEM_VALOR_INSCRITO_DESCONHECIDO,
    ORIGEM_VALOR_TRAFEGO_PAGO,
)
from domain.coupons import (
    _DEFAULT_ASSESSOR_POR_CUPOM,
    _DEFAULT_ORIGEM_POR_CUPOM_CANAL,
    resolve_assessor_and_origem,
)


def _resolve(cupom):
    return resolve_assessor_and_origem(cupom, _DEFAULT_ASSESSOR_POR_CUPOM, _DEFAULT_ORIGEM_POR_CUPOM_CANAL)


def test_sem_cupom_e_inscrito_desconhecido():
    assert _resolve("") == (None, ORIGEM_VALOR_INSCRITO_DESCONHECIDO)
    assert _resolve(None) == (None, ORIGEM_VALOR_INSCRITO_DESCONHECIDO)


def test_cupom_de_assessor_mapeado():
    cupom, email = next(iter(_DEFAULT_ASSESSOR_POR_CUPOM.items()))
    assert _resolve(cupom) == (email, ORIGEM_VALOR_CUPOM_DESCONTO)


def test_cupom_case_insensitive_e_com_espacos():
    cupom, email = next(iter(_DEFAULT_ASSESSOR_POR_CUPOM.items()))
    variante = f"  {cupom.lower()}  "
    assert _resolve(variante) == (email, ORIGEM_VALOR_CUPOM_DESCONTO)


def test_cupom_de_canal_nao_atribui_responsavel():
    cupom = next(iter(_DEFAULT_ORIGEM_POR_CUPOM_CANAL))
    assert _resolve(cupom) == (None, ORIGEM_VALOR_TRAFEGO_PAGO)


def test_cupom_nao_mapeado_cai_no_default_e_avisa(caplog):
    with caplog.at_level("WARNING"):
        result = _resolve("100.00% - NINGUEM-CONHECE-ESSE")
    assert result == (None, ORIGEM_VALOR_INSCRITO_DESCONHECIDO)
    assert "não mapeado" in caplog.text


def test_mapas_customizados_sobrescrevem_o_default():
    """Confirma que a função é de fato pura/parametrizada — passar mapas
    diferentes dos _DEFAULT_* muda o resultado."""
    result = resolve_assessor_and_origem("CUPOM-X", {"CUPOM-X": "fulano@empresa.com"}, {})
    assert result == ("fulano@empresa.com", ORIGEM_VALOR_CUPOM_DESCONTO)
