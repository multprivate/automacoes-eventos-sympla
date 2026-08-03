from common.normalization import (
    build_cupom_by_order_id,
    extract_discount_code,
    extract_phone,
    format_event_label,
    format_phone_br,
    normalize_cupom,
    normalize_email,
    normalize_name,
    participant_full_name,
)


class TestNormalizeName:
    def test_remove_acentos_e_maiuscula(self):
        assert normalize_name("João Ferreira") == "joao ferreira"

    def test_colapsa_espacos(self):
        assert normalize_name("  Maria   Silva  ") == "maria silva"

    def test_vazio(self):
        assert normalize_name("") == ""
        assert normalize_name(None) == ""


class TestNormalizeEmail:
    def test_lowercase_e_strip(self):
        assert normalize_email(" Joao@Empresa.COM ") == "joao@empresa.com"


class TestFormatPhoneBr:
    def test_adiciona_ddi_55(self):
        assert format_phone_br("85999998888") == "+5585999998888"

    def test_ja_tem_ddi(self):
        assert format_phone_br("5585999998888") == "+5585999998888"

    def test_remove_caracteres_nao_numericos(self):
        assert format_phone_br("(85) 99999-8888") == "+5585999998888"

    def test_vazio(self):
        assert format_phone_br("") == ""
        assert format_phone_br(None) == ""


class TestExtractPhone:
    def test_encontra_por_palavra_chave_telefone(self):
        participant = {"custom_form": [{"name": "Telefone para contato", "value": "85999998888"}]}
        assert extract_phone(participant) == "85999998888"

    def test_encontra_por_whatsapp(self):
        participant = {"custom_form": [{"name": "WhatsApp/Telefone", "value": "85988887777"}]}
        assert extract_phone(participant) == "85988887777"

    def test_encontra_por_celular(self):
        participant = {"custom_form": [{"name": "Celular", "value": "85977776666"}]}
        assert extract_phone(participant) == "85977776666"

    def test_sem_campo_de_telefone(self):
        participant = {"custom_form": [{"name": "Empresa", "value": "Acme"}]}
        assert extract_phone(participant) == ""

    def test_sem_custom_form(self):
        assert extract_phone({}) == ""


class TestParticipantFullName:
    def test_junta_nome_e_sobrenome(self):
        assert participant_full_name({"first_name": "Maria", "last_name": "Silva"}) == "Maria Silva"

    def test_sem_sobrenome(self):
        assert participant_full_name({"first_name": "Maria", "last_name": ""}) == "Maria"


class TestExtractDiscountCode:
    """A armadilha documentada em ARQUITETURA.md: a Sympla usa a string
    "0"/"0.00" pra dizer "sem desconto" — não é vazia/None, então um
    `if valor:` ingênuo trataria isso como cupom de verdade."""

    def test_cupom_direto_no_participante(self):
        participant = {"order_discount": "100.00% - BRUNA"}
        assert extract_discount_code(participant, lambda: {}) == "100.00% - BRUNA"

    def test_zero_no_participante_nao_conta_como_cupom(self):
        participant = {"order_discount": "0", "order_id": "123"}
        assert extract_discount_code(participant, lambda: {"123": "100.00% - IARA"}) == "100.00% - IARA"

    def test_zero_ponto_zero_zero_nao_conta_como_cupom(self):
        participant = {"order_discount": "0.00", "order_id": "123"}
        assert extract_discount_code(participant, lambda: {"123": "100.00% - IARA"}) == "100.00% - IARA"

    def test_fallback_pro_mapa_de_orders(self):
        participant = {"order_discount": "", "order_id": "456"}
        assert extract_discount_code(participant, lambda: {"456": "100.00% - MILETO"}) == "100.00% - MILETO"

    def test_sem_order_id_retorna_vazio(self):
        participant = {"order_discount": ""}
        assert extract_discount_code(participant, lambda: {}) == ""

    def test_nao_busca_orders_se_ja_achou_direto(self):
        """get_cupom_by_order_id é preguiçoso — não deve ser chamado se o
        campo direto já resolveu."""
        called = []

        def get_map():
            called.append(True)
            return {}

        extract_discount_code({"order_discount": "100.00% - BRUNA"}, get_map)
        assert called == []


class TestBuildCupomByOrderId:
    def test_mapeia_discount_code_por_id(self):
        orders = [{"id": 1, "discount_code": "100.00% - IARA"}, {"id": 2, "discount_code": "0"}]
        result = build_cupom_by_order_id(orders)
        assert result["1"] == "100.00% - IARA"
        assert result["2"] == ""

    def test_ignora_orders_sem_id(self):
        assert build_cupom_by_order_id([{"discount_code": "X"}]) == {}


class TestNormalizeCupom:
    def test_trim_e_upper(self):
        assert normalize_cupom("  100.00% - iara  ") == "100.00% - IARA"


class TestFormatEventLabel:
    def test_formata_data_br(self):
        assert format_event_label("Workshop", "2026-03-04") == "04/03/26 - Workshop"

    def test_data_invalida_usa_placeholder(self):
        assert format_event_label("Workshop", "") == "??/??/?? - Workshop"

    def test_identico_para_mesmo_input(self):
        """Garantia crítica: setup_custom_fields.py (backfill em massa) e
        automacao_a_inscricoes.py (incremental) precisam gerar o MESMO
        texto pro mesmo evento, ou o Bitrix ganha itens de lista duplicados."""
        a = format_event_label("IMAGEM É PATRIMÔNIO", "2026-08-03")
        b = format_event_label("IMAGEM É PATRIMÔNIO", "2026-08-03")
        assert a == b
