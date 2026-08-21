from interface.inscritos_helper import build_inscritos_view, filter_linhas, montar_funil_barras, resumo_conversao


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


class TestMontarFunilBarras:
    def test_nenhum_dado_retorna_none(self):
        assert montar_funil_barras(None) is None

    def test_percentuais_relativos_ao_primeiro_degrau(self):
        funil = {"inscrito": 10, "pos_evento": 8, "reuniao": 4, "convertido": 2, "perdido": 1, "fora_do_funil": 0, "total": 11}
        barras = montar_funil_barras(funil)

        assert [b["chave"] for b in barras] == ["inscrito", "pos_evento", "reuniao", "convertido"]
        assert barras[0] == {"chave": "inscrito", "rotulo": "Inscritos pro evento", "valor": 10, "pct": 100}
        assert barras[1]["pct"] == 80
        assert barras[2]["pct"] == 40
        assert barras[3]["pct"] == 20

    def test_sem_ninguem_inscrito_nao_divide_por_zero(self):
        funil = {"inscrito": 0, "pos_evento": 0, "reuniao": 0, "convertido": 0, "perdido": 0, "fora_do_funil": 0, "total": 0}
        barras = montar_funil_barras(funil)
        assert all(b["pct"] == 0 for b in barras)


class TestFilterLinhas:
    def _linhas(self):
        return [
            {"nome": "Karine Gomes", "email": "karine@example.com", "status": "prospect"},
            {"nome": "Paulo Salim", "email": "paulo@example.com", "status": "cliente"},
            {"nome": "Elienai Luz", "email": "elienai@hotmail.com", "status": "cliente"},
        ]

    def test_sem_filtro_retorna_tudo(self):
        assert filter_linhas(self._linhas()) == self._linhas()

    def test_filtra_por_nome_parcial_case_insensitive(self):
        resultado = filter_linhas(self._linhas(), q="karine")
        assert [l["nome"] for l in resultado] == ["Karine Gomes"]

    def test_filtra_por_email_parcial(self):
        resultado = filter_linhas(self._linhas(), q="hotmail")
        assert [l["nome"] for l in resultado] == ["Elienai Luz"]

    def test_filtra_por_status(self):
        resultado = filter_linhas(self._linhas(), status="cliente")
        assert {l["nome"] for l in resultado} == {"Paulo Salim", "Elienai Luz"}

    def test_combina_busca_e_status(self):
        resultado = filter_linhas(self._linhas(), q="e", status="cliente")
        assert {l["nome"] for l in resultado} == {"Paulo Salim", "Elienai Luz"}

    def test_sem_resultado(self):
        assert filter_linhas(self._linhas(), q="ninguem-com-esse-nome") == []


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
