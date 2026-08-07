from interface.filters import to_brt


def test_converte_utc_pra_horario_de_brasilia():
    assert to_brt("2026-08-07T14:00:00+00:00") == "07/08/2026 11:00"


def test_aceita_string_utc_sem_offset_explicito():
    assert to_brt("2026-08-07T14:00:00") == "07/08/2026 11:00"


def test_vazio_retorna_vazio():
    assert to_brt(None) == ""
    assert to_brt("") == ""


def test_string_invalida_retorna_original():
    assert to_brt("não é uma data") == "não é uma data"
