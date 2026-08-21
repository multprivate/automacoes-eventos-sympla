from domain.funil_conversao import classificar_lead, resumo_funil

STAGE_INSCRITO = "NEWINSCRITO"
STAGE_POS_EVENTO = "NEWPOSEVENTO"
STAGE_REUNIAO = "UC_TJ9FPC"


class TestClassificarLead:
    def test_inscrito(self):
        assert classificar_lead(STAGE_INSCRITO, STAGE_INSCRITO, STAGE_POS_EVENTO, STAGE_REUNIAO) == "inscrito"

    def test_pos_evento(self):
        assert classificar_lead(STAGE_POS_EVENTO, STAGE_INSCRITO, STAGE_POS_EVENTO, STAGE_REUNIAO) == "pos_evento"

    def test_reuniao(self):
        assert classificar_lead(STAGE_REUNIAO, STAGE_INSCRITO, STAGE_POS_EVENTO, STAGE_REUNIAO) == "reuniao"

    def test_convertido(self):
        assert classificar_lead("CONVERTED", STAGE_INSCRITO, STAGE_POS_EVENTO, STAGE_REUNIAO) == "convertido"

    def test_espolio_conta_como_reuniao_mas_nao_convertido(self):
        """NEWESPOLIO fica entre Reunião e Convertido na ordem do funil —
        chegou até a reunião, mas não virou negócio."""
        assert classificar_lead("NEWESPOLIO", STAGE_INSCRITO, STAGE_POS_EVENTO, STAGE_REUNIAO) == "reuniao"

    def test_junk_e_perdido_isolado(self):
        assert classificar_lead("JUNK", STAGE_INSCRITO, STAGE_POS_EVENTO, STAGE_REUNIAO) == "perdido"

    def test_estagio_de_funil_antigo_e_fora_do_funil(self):
        """Lead vinculado ao evento mas parado no funil antigo (nunca
        promovido — ver services/lead_sync_service.py) não mapeia pra
        nenhum dos 4 degraus."""
        assert classificar_lead("IN_PROCESS", STAGE_INSCRITO, STAGE_POS_EVENTO, STAGE_REUNIAO) == "fora_do_funil"
        assert classificar_lead("UC_VL3WIF", STAGE_INSCRITO, STAGE_POS_EVENTO, STAGE_REUNIAO) == "fora_do_funil"

    def test_estagio_desconhecido_e_fora_do_funil(self):
        assert classificar_lead("ALGUM_ESTAGIO_NOVO_NAO_MAPEADO", STAGE_INSCRITO, STAGE_POS_EVENTO, STAGE_REUNIAO) == "fora_do_funil"

    def test_status_none_e_fora_do_funil(self):
        assert classificar_lead(None, STAGE_INSCRITO, STAGE_POS_EVENTO, STAGE_REUNIAO) == "fora_do_funil"

    def test_newlead_e_newfup_ainda_nao_chegaram_no_funil(self):
        assert classificar_lead("NEWLEAD", STAGE_INSCRITO, STAGE_POS_EVENTO, STAGE_REUNIAO) == "fora_do_funil"
        assert classificar_lead("NEWFUP", STAGE_INSCRITO, STAGE_POS_EVENTO, STAGE_REUNIAO) == "fora_do_funil"


class TestResumoFunil:
    def test_cumulativo_convertido_soma_em_todos_os_degraus(self):
        leads = [{"STATUS_ID": "CONVERTED"}]
        resumo = resumo_funil(leads, STAGE_INSCRITO, STAGE_POS_EVENTO, STAGE_REUNIAO)

        assert resumo["inscrito"] == 1
        assert resumo["pos_evento"] == 1
        assert resumo["reuniao"] == 1
        assert resumo["convertido"] == 1
        assert resumo["total"] == 1

    def test_mistura_de_estagios(self):
        leads = [
            {"STATUS_ID": STAGE_INSCRITO},
            {"STATUS_ID": STAGE_INSCRITO},
            {"STATUS_ID": STAGE_POS_EVENTO},
            {"STATUS_ID": STAGE_REUNIAO},
            {"STATUS_ID": "CONVERTED"},
            {"STATUS_ID": "JUNK"},
            {"STATUS_ID": "IN_PROCESS"},
        ]
        resumo = resumo_funil(leads, STAGE_INSCRITO, STAGE_POS_EVENTO, STAGE_REUNIAO)

        assert resumo["inscrito"] == 5  # todos exceto JUNK e IN_PROCESS
        assert resumo["pos_evento"] == 3  # pos_evento, reuniao, convertido
        assert resumo["reuniao"] == 2  # reuniao, convertido
        assert resumo["convertido"] == 1
        assert resumo["perdido"] == 1
        assert resumo["fora_do_funil"] == 1
        assert resumo["total"] == 7

    def test_lista_vazia(self):
        resumo = resumo_funil([], STAGE_INSCRITO, STAGE_POS_EVENTO, STAGE_REUNIAO)
        assert resumo == {"inscrito": 0, "pos_evento": 0, "reuniao": 0, "convertido": 0, "perdido": 0, "fora_do_funil": 0, "total": 0}
