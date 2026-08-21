from interface.inscritos_helper import build_inscritos_view, resumo_conversao


def _participant(pid: str, nome="Fulano Teste", email="fulano@example.com", checked_in=False) -> dict:
    return {
        "id": pid,
        "first_name": nome.split()[0],
        "last_name": " ".join(nome.split()[1:]),
        "email": email,
        "custom_form": [
            {"name": "Telefone", "value": "(85) 99999-0000"},
            {"name": "CPF", "value": "057.077.113-76"},
        ],
        "checkin": {"check_in_date": "2026-01-01"} if checked_in else {},
    }


def test_inscrito_sem_linha_correspondente_e_nao_verificado():
    linhas = build_inscritos_view([_participant("1")], resultados={})

    assert len(linhas) == 1
    assert linhas[0]["status"] == "nao_verificado"
    assert linhas[0]["processado_em"] is None
    assert linhas[0]["tem_duplicado"] is False


def test_linha_legada_pre_migracao_0006_e_nao_verificada_mas_tem_data_encontrado():
    """Linha existente antes da migração 0006: processado_em real, mas as
    colunas novas (is_cliente etc) são None — sem backfill possível."""
    resultados = {"1": {"participant_id": "1", "processado_em": "2025-06-01T00:00:00+00:00", "is_cliente": None, "match_method": None}}
    linhas = build_inscritos_view([_participant("1")], resultados)

    assert linhas[0]["status"] == "nao_verificado"
    assert linhas[0]["processado_em"] == "2025-06-01T00:00:00+00:00"


def test_inscrito_cliente_com_match_e_reconhecido():
    resultados = {"1": {"participant_id": "1", "is_cliente": True, "match_method": "cpf", "bitrix_contact_id": 42, "bitrix_lead_id": 7, "processado_em": "2026-01-01T00:00:00+00:00", "verificado_em": "2026-01-02T00:00:00+00:00"}}
    linhas = build_inscritos_view([_participant("1")], resultados)

    assert linhas[0]["status"] == "cliente"
    assert linhas[0]["match_method"] == "cpf"
    assert linhas[0]["contact_id"] == 42
    assert linhas[0]["lead_id"] == 7


def test_inscrito_prospect_sem_contato_e_reconhecido():
    resultados = {"1": {"participant_id": "1", "is_cliente": False, "match_method": "telefone", "bitrix_lead_id": 9}}
    linhas = build_inscritos_view([_participant("1")], resultados)

    assert linhas[0]["status"] == "prospect"
    assert linhas[0]["contact_id"] is None
    assert linhas[0]["lead_id"] == 9


def test_inscrito_com_contatos_duplicados_marca_tem_duplicado():
    resultados = {"1": {"participant_id": "1", "is_cliente": True, "match_method": "telefone", "bitrix_contact_id": 538, "contact_ids_duplicados": [25216, 538]}}
    linhas = build_inscritos_view([_participant("1")], resultados)

    assert linhas[0]["tem_duplicado"] is True
    assert linhas[0]["contact_ids_duplicados"] == [25216, 538]


def test_checkin_extraido_do_participante():
    linhas = build_inscritos_view([_participant("1", checked_in=True), _participant("2", checked_in=False)], resultados={})
    assert linhas[0]["checkin"] is True
    assert linhas[1]["checkin"] is False


class TestResumoConversao:
    def test_taxa_considera_so_verificados_no_denominador(self):
        linhas = [
            {"status": "cliente"}, {"status": "cliente"},
            {"status": "prospect"},
            {"status": "nao_verificado"}, {"status": "nao_verificado"},
        ]
        resumo = resumo_conversao(linhas)

        assert resumo["total"] == 5
        assert resumo["clientes"] == 2
        assert resumo["prospects"] == 1
        assert resumo["nao_verificados"] == 2
        assert resumo["taxa_pct"] == 67  # 2 de 3 verificados, arredondado

    def test_ninguem_verificado_ainda_nao_divide_por_zero(self):
        linhas = [{"status": "nao_verificado"}, {"status": "nao_verificado"}]
        resumo = resumo_conversao(linhas)

        assert resumo["taxa_pct"] == 0
        assert resumo["nao_verificados"] == 2

    def test_lista_vazia(self):
        resumo = resumo_conversao([])
        assert resumo == {"total": 0, "clientes": 0, "prospects": 0, "nao_verificados": 0, "taxa_pct": 0}
