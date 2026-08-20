from services import lead_sync_service


def test_filtra_evento_inativo(monkeypatch):
    monkeypatch.setattr(
        lead_sync_service.eventos_config_repo,
        "get_all",
        lambda: [{"sympla_event_id": "e1", "ativo": False, "removido_em": None}],
    )
    events = [{"id": "e1"}, {"id": "e2"}]
    result = lead_sync_service._filter_eventos_ativos(events)
    assert [e["id"] for e in result] == ["e2"]


def test_filtra_evento_removido(monkeypatch):
    monkeypatch.setattr(
        lead_sync_service.eventos_config_repo,
        "get_all",
        lambda: [{"sympla_event_id": "e1", "ativo": True, "removido_em": "2026-01-01T00:00:00Z"}],
    )
    events = [{"id": "e1"}, {"id": "e2"}]
    result = lead_sync_service._filter_eventos_ativos(events)
    assert [e["id"] for e in result] == ["e2"]


def test_evento_sem_config_e_tratado_como_ativo(monkeypatch):
    monkeypatch.setattr(lead_sync_service.eventos_config_repo, "get_all", lambda: [])
    events = [{"id": "e1"}, {"id": "e2"}]
    result = lead_sync_service._filter_eventos_ativos(events)
    assert result == events


def test_falha_ao_ler_eventos_config_e_fail_aberto(monkeypatch):
    def _raise():
        raise RuntimeError("supabase fora do ar")

    monkeypatch.setattr(lead_sync_service.eventos_config_repo, "get_all", _raise)
    events = [{"id": "e1"}, {"id": "e2"}]
    result = lead_sync_service._filter_eventos_ativos(events)
    assert result == events


class TestFindMatchingLeadIdsWrapper:
    def test_email_bate_mas_nome_diverge_usa_get_lead_pra_confirmar_e_rejeita(self, monkeypatch):
        """Reproduz o caso real do cupom em grupo (mesmo e-mail, inscritos
        diferentes): a busca por e-mail acha um candidato, mas o nome dele
        (resolvido via get_lead, um crm.lead.get de verdade) não bate com o
        inscrito -> o wrapper rejeita e cai pro passo de busca por nome."""
        get_lead_calls = []

        def fake_get_lead(lead_id):
            get_lead_calls.append(lead_id)
            return {"ID": lead_id, "NAME": "Gabriel Prado"}

        monkeypatch.setattr(lead_sync_service, "get_lead", fake_get_lead)
        monkeypatch.setattr(lead_sync_service, "find_lead_ids_by_phone", lambda phone: [])
        monkeypatch.setattr(lead_sync_service, "find_lead_ids_by_email", lambda email: [3])
        monkeypatch.setattr(lead_sync_service, "find_lead_ids_by_name", lambda name: [])

        ids, method = lead_sync_service.find_matching_lead_ids("", "", "rcparanegocios@gmail.com", "Natan Prado")

        assert ids == []
        assert method is None
        assert get_lead_calls == [3]


PARTICIPANT = {"id": "999"}
STATS = lambda: {"eventos_processados": 0, "leads_criados": 0, "leads_atualizados": 0, "erros": 0}


class TestProcessClienteParticipant:
    def test_contato_sem_lead_deste_evento_cria_lead_novo(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: {} if method == "crm.contact.get" else calls.append((method, payload)))
        monkeypatch.setattr(lead_sync_service, "_find_lead_ids_for_contact_linked_to_event", lambda contact_id, item_id: [])
        monkeypatch.setattr(lead_sync_service, "create_lead_from_participant", lambda *a, **kw: calls.append(("create_lead", kw)))

        stats = STATS()
        lead_sync_service._process_cliente_participant(
            [42], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, {}, "", {}, [], item_id=28, force=False, event_already_happened=False, checked_in=False,
        )

        assert any(m == "create_lead" for m, _ in calls)
        create_kwargs = next(kw for m, kw in calls if m == "create_lead")
        assert create_kwargs["contact_id"] == 42
        assert create_kwargs["item_id"] == 28

    def test_contato_com_lead_deste_evento_so_atualiza_nao_cria(self, monkeypatch):
        """Regra de negócio: um Contato pode ter OUTRO Lead aberto em outro
        estágio (negociação paralela) — isso não é mais consultado nem
        impede a criação do Lead do evento. O que impede é só já existir um
        Lead vinculado a ESTE evento."""
        calls = []
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: calls.append((method, payload)) or {})
        monkeypatch.setattr(lead_sync_service, "get_lead", lambda lead_id: {"ID": lead_id})
        monkeypatch.setattr(lead_sync_service, "_find_lead_ids_for_contact_linked_to_event", lambda contact_id, item_id: [777])
        monkeypatch.setattr(lead_sync_service, "create_lead_from_participant", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("não deveria criar Lead novo")))

        stats = STATS()
        lead_sync_service._process_cliente_participant(
            [42], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, {}, "", {}, [], item_id=28, force=False, event_already_happened=False, checked_in=False,
        )

        lead_update_calls = [payload for method, payload in calls if method == "crm.lead.update"]
        assert len(lead_update_calls) == 1
        assert lead_update_calls[0]["id"] == 777
        assert lead_update_calls[0]["fields"] == {lead_sync_service.FIELD_PARENT_ID_EVENTO_SPA: 28}
        assert stats["leads_atualizados"] == 1

    def test_contato_com_lead_aberto_em_outro_estagio_ainda_assim_cria_lead_do_evento(self, monkeypatch):
        """Trava a regra de negócio confirmada: um Lead de negociação
        paralela do Contato (aberto em outro estágio, não vinculado a este
        evento) NUNCA impede nem é tocado pela criação do Lead do evento."""
        calls = []
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: {} if method == "crm.contact.get" else calls.append((method, payload)))
        # Nenhum Lead vinculado a ESTE evento ainda, mesmo que o Contato
        # tenha outro Lead aberto em algum lugar (não é mais consultado).
        monkeypatch.setattr(lead_sync_service, "_find_lead_ids_for_contact_linked_to_event", lambda contact_id, item_id: [])
        monkeypatch.setattr(lead_sync_service, "create_lead_from_participant", lambda *a, **kw: calls.append(("create_lead", kw)))

        stats = STATS()
        lead_sync_service._process_cliente_participant(
            [42], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, {}, "", {}, [], item_id=28, force=False, event_already_happened=False, checked_in=False,
        )

        assert any(m == "create_lead" for m, _ in calls)
        assert not any(method == "crm.lead.update" for method, _ in calls)

    def test_force_rerun_nao_duplica_lead_do_evento(self, monkeypatch):
        """Idempotência sob 'Forçar atualização de campos': reprocessar o
        mesmo participante depois que o Lead do evento já existe atualiza
        em vez de criar um segundo."""
        calls = []
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: {} if method == "crm.contact.get" else calls.append((method, payload)))
        monkeypatch.setattr(lead_sync_service, "get_lead", lambda lead_id: {"ID": lead_id})
        monkeypatch.setattr(lead_sync_service, "create_lead_from_participant", lambda *a, **kw: calls.append(("create_lead", kw)))

        # 1ª rodada: ainda não existe Lead deste evento -> cria.
        monkeypatch.setattr(lead_sync_service, "_find_lead_ids_for_contact_linked_to_event", lambda contact_id, item_id: [])
        stats = STATS()
        lead_sync_service._process_cliente_participant(
            [42], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, {}, "", {}, [], item_id=28, force=True, event_already_happened=False, checked_in=False,
        )
        assert sum(1 for m, _ in calls if m == "create_lead") == 1
        assert not any(m == "crm.lead.update" for m, _ in calls)

        # 2ª rodada (force rerun): já existe o Lead #999 deste evento -> só atualiza.
        monkeypatch.setattr(lead_sync_service, "_find_lead_ids_for_contact_linked_to_event", lambda contact_id, item_id: [999])
        lead_sync_service._process_cliente_participant(
            [42], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, {}, "", {}, [], item_id=28, force=True, event_already_happened=False, checked_in=False,
        )
        assert sum(1 for m, _ in calls if m == "create_lead") == 1
        lead_update_calls = [payload for m, payload in calls if m == "crm.lead.update"]
        assert len(lead_update_calls) == 1
        assert lead_update_calls[0]["id"] == 999

    def test_contato_ja_vinculado_ao_item_nao_reenvia(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: calls.append((method, payload)) or {lead_sync_service.FIELD_PARENT_ID_EVENTO_SPA: 28})
        monkeypatch.setattr(lead_sync_service, "_find_lead_ids_for_contact_linked_to_event", lambda contact_id, item_id: [777])
        monkeypatch.setattr(lead_sync_service, "get_lead", lambda lead_id: {"ID": lead_id, lead_sync_service.FIELD_PARENT_ID_EVENTO_SPA: 28})

        stats = STATS()
        lead_sync_service._process_cliente_participant(
            [42], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, {}, "", {}, [], item_id=28, force=False, event_already_happened=False, checked_in=False,
        )

        assert not any(method == "crm.contact.update" for method, _ in calls)
        assert not any(method == "crm.lead.update" for method, _ in calls)

    def test_multiplos_contatos_usa_so_o_de_menor_id_e_loga_duplicado(self, monkeypatch):
        create_calls = []
        log_calls = []
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: {})
        monkeypatch.setattr(lead_sync_service, "_find_lead_ids_for_contact_linked_to_event", lambda contact_id, item_id: [])
        monkeypatch.setattr(lead_sync_service, "create_lead_from_participant", lambda *a, **kw: create_calls.append(kw))
        monkeypatch.setattr(lead_sync_service.logs_repo, "insert_item", lambda *a, **kw: log_calls.append((a, kw)))

        stats = STATS()
        lead_sync_service._process_cliente_participant(
            [25216, 538], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, {}, "", {}, [], item_id=28, force=False, event_already_happened=False, checked_in=False,
        )

        # só processa o de menor ID (538), não cria um Lead pra cada Contato
        assert len(create_calls) == 1
        assert create_calls[0]["contact_id"] == 538

        # registra o duplicado achado, pra revisão manual
        assert len(log_calls) == 1
        args, kwargs = log_calls[0]
        assert args[0] == "CONTATO_DUPLICADO"
        assert kwargs["detalhes"]["contact_ids"] == [25216, 538]
        assert kwargs["detalhes"]["contact_id_usado"] == 538


class TestProcessParticipantDispatch:
    def test_contato_encontrado_vai_pro_branch_cliente(self, monkeypatch):
        monkeypatch.setattr(lead_sync_service, "find_matching_contact_ids", lambda cpf, phone, email: ([42], "telefone"))
        monkeypatch.setattr(lead_sync_service, "_process_cliente_participant", lambda *a, **kw: None)
        monkeypatch.setattr(
            lead_sync_service, "find_matching_lead_ids",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("não deveria cair na cascata de Lead")),
        )

        stats = STATS()
        field_config = {"field_data_do_evento": "", "field_nome_do_evento": "", "field_sympla_event_id": "", "field_filtrar_evento": "", "field_origem": "", "stage_alvo": ""}
        result = lead_sync_service.process_participant(
            {"id": "1", "email": "a@b.com"}, "Evento", "2026-01-01", "e1", "", lambda: {}, stats, field_config, [],
        )
        assert result is True

    def test_sem_contato_cai_na_cascata_de_lead(self, monkeypatch):
        monkeypatch.setattr(lead_sync_service, "find_matching_contact_ids", lambda cpf, phone, email: ([], None))
        monkeypatch.setattr(lead_sync_service, "find_matching_lead_ids", lambda *a, **kw: ([], None))

        stats = STATS()
        field_config = {"field_data_do_evento": "", "field_nome_do_evento": "", "field_sympla_event_id": "", "field_filtrar_evento": "", "field_origem": "", "stage_alvo": ""}
        result = lead_sync_service.process_participant(
            {"id": "1", "email": ""}, "Evento", "2026-01-01", "e1", "", lambda: {}, stats, field_config, [],
        )
        assert result is True  # sem telefone/e-mail/nome batendo -> pulado, mas tratado como sucesso


def _lead_cascata_field_config(field_cpf_lead: str = "") -> dict:
    return {
        "field_data_do_evento": "", "field_nome_do_evento": "", "field_sympla_event_id": "",
        "field_filtrar_evento": "", "field_origem": "", "stage_alvo": "NEWINSCRITO",
        "field_presente_no_evento": "", "stage_pos_evento": "NEWPOSEVENTO",
        "field_cpf_lead": field_cpf_lead, "field_cpf_contact": "",
    }


CLIENTE_CPF_PARTICIPANT = {
    "id": "500", "first_name": "Maria", "last_name": "Silva",
    "custom_form": [
        {"name": "Telefone", "value": "(85) 99999-0000"},
        {"name": "CPF", "value": "057.077.113-76"},
    ],
}


class TestProcessParticipantLeadFechado:
    """Regra confirmada: um Lead já fechado (JUNK/CONVERTED) encontrado
    pela cascata nunca é reaberto sozinho — a inscrição gera um Lead novo
    em vez disso, mesmo princípio já aplicado à correção do Contato com
    Lead aberto em outro estágio."""

    def test_so_lead_fechado_cria_lead_novo_sem_tocar_nele(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "find_matching_contact_ids", lambda cpf, phone, email: ([], None))
        monkeypatch.setattr(lead_sync_service, "find_matching_lead_ids", lambda cpf, phone, email, name: ([54830], "telefone"))
        monkeypatch.setattr(lead_sync_service, "get_lead", lambda lead_id: {"ID": lead_id, "STATUS_ID": "JUNK"})
        monkeypatch.setattr(lead_sync_service, "create_lead_from_participant", lambda *a, **kw: calls.append(("create_lead", kw)))
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: (_ for _ in ()).throw(AssertionError(f"não deveria chamar {method}")))

        stats = STATS()
        result = lead_sync_service.process_participant(
            CLIENTE_CPF_PARTICIPANT, "Evento", "2026-01-01", "e1", "", lambda: {}, stats, _lead_cascata_field_config(), [],
        )

        assert result is True
        assert len(calls) == 1
        assert calls[0][0] == "create_lead"  # só a chamada de criação, nenhum bitrix_call direto
        assert calls[0][1]["item_id"] is None

    def test_lead_aberto_e_fechado_juntos_so_atualiza_o_aberto(self, monkeypatch):
        leads = {1: {"ID": 1, "STATUS_ID": "NEWLEAD"}, 2: {"ID": 2, "STATUS_ID": "CONVERTED"}}
        calls = []
        monkeypatch.setattr(lead_sync_service, "find_matching_contact_ids", lambda cpf, phone, email: ([], None))
        monkeypatch.setattr(lead_sync_service, "find_matching_lead_ids", lambda cpf, phone, email, name: ([1, 2], "telefone"))
        monkeypatch.setattr(lead_sync_service, "get_lead", lambda lead_id: leads[lead_id])
        monkeypatch.setattr(lead_sync_service, "create_lead_from_participant", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("não deveria criar Lead novo — já tem um aberto")))
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: calls.append((method, payload)) or {})

        stats = STATS()
        lead_sync_service.process_participant(
            CLIENTE_CPF_PARTICIPANT, "Evento", "2026-01-01", "e1", "", lambda: {}, stats, _lead_cascata_field_config(), [],
        )

        lead_update_calls = [payload for m, payload in calls if m == "crm.lead.update"]
        assert len(lead_update_calls) == 1
        assert lead_update_calls[0]["id"] == 1

    def test_lead_aberto_em_funil_antigo_continua_sem_mudar_estagio(self, monkeypatch):
        """Regressão: fora do escopo desta correção — um Lead aberto fora
        de NEWLEAD/NEWFUP (mas NÃO fechado) continua só ganhando os campos
        de evento, sem promoção de estágio, exatamente como antes."""
        calls = []
        monkeypatch.setattr(lead_sync_service, "find_matching_contact_ids", lambda cpf, phone, email: ([], None))
        monkeypatch.setattr(lead_sync_service, "find_matching_lead_ids", lambda cpf, phone, email, name: ([1], "telefone"))
        monkeypatch.setattr(lead_sync_service, "get_lead", lambda lead_id: {"ID": 1, "STATUS_ID": "UC_Z0M384"})
        monkeypatch.setattr(lead_sync_service, "create_lead_from_participant", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("não deveria criar Lead novo")))
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: calls.append((method, payload)) or {})

        field_config = {**_lead_cascata_field_config(), "field_data_do_evento": "UF_DATA_EVENTO"}
        stats = STATS()
        lead_sync_service.process_participant(
            CLIENTE_CPF_PARTICIPANT, "Evento", "2026-01-01", "e1", "", lambda: {}, stats, field_config, [],
        )

        lead_update_calls = [payload for m, payload in calls if m == "crm.lead.update"]
        assert len(lead_update_calls) == 1
        assert lead_update_calls[0]["fields"]["UF_DATA_EVENTO"] == "2026-01-01"
        assert "STATUS_ID" not in lead_update_calls[0]["fields"]


class TestProcessParticipantPreencheCpf:
    def test_lead_criado_ganha_cpf_do_inscrito(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "find_matching_contact_ids", lambda cpf, phone, email: ([], None))
        monkeypatch.setattr(lead_sync_service, "find_matching_lead_ids", lambda cpf, phone, email, name: ([], None))
        monkeypatch.setattr(lead_sync_service, "resolve_assessor_and_origem", lambda cupom: (None, "Inscrito Desconhecido"))
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: calls.append((method, payload)) or "123")

        stats = STATS()
        lead_sync_service.process_participant(
            CLIENTE_CPF_PARTICIPANT, "Evento", "2026-01-01", "e1", "", lambda: {}, stats,
            _lead_cascata_field_config(field_cpf_lead="UF_CPF"), [],
        )

        add_payload = next(p for m, p in calls if m == "crm.lead.add")
        assert add_payload["fields"]["UF_CPF"] == "05707711376"

    def test_lead_matched_sem_cpf_e_preenchido(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "find_matching_contact_ids", lambda cpf, phone, email: ([], None))
        monkeypatch.setattr(lead_sync_service, "find_matching_lead_ids", lambda cpf, phone, email, name: ([1], "telefone"))
        monkeypatch.setattr(lead_sync_service, "get_lead", lambda lead_id: {"ID": 1, "STATUS_ID": "NEWLEAD"})
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: calls.append((method, payload)) or {})

        stats = STATS()
        lead_sync_service.process_participant(
            CLIENTE_CPF_PARTICIPANT, "Evento", "2026-01-01", "e1", "", lambda: {}, stats,
            _lead_cascata_field_config(field_cpf_lead="UF_CPF"), [],
        )

        lead_update_calls = [payload for m, payload in calls if m == "crm.lead.update"]
        assert lead_update_calls[0]["fields"]["UF_CPF"] == "05707711376"

    def test_lead_matched_com_cpf_ja_preenchido_nao_sobrescreve(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "find_matching_contact_ids", lambda cpf, phone, email: ([], None))
        monkeypatch.setattr(lead_sync_service, "find_matching_lead_ids", lambda cpf, phone, email, name: ([1], "telefone"))
        monkeypatch.setattr(lead_sync_service, "get_lead", lambda lead_id: {"ID": 1, "STATUS_ID": "NEWLEAD", "UF_CPF": "11122233344"})
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: calls.append((method, payload)) or {})

        stats = STATS()
        lead_sync_service.process_participant(
            CLIENTE_CPF_PARTICIPANT, "Evento", "2026-01-01", "e1", "", lambda: {}, stats,
            _lead_cascata_field_config(field_cpf_lead="UF_CPF"), [],
        )

        lead_update_calls = [payload for m, payload in calls if m == "crm.lead.update"]
        assert not lead_update_calls or "UF_CPF" not in lead_update_calls[0]["fields"]


class TestProcessClienteParticipantPreencheCpfContato:
    def test_contato_sem_cpf_e_preenchido(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: {"ID": 42} if method == "crm.contact.get" else calls.append((method, payload)) or {})
        monkeypatch.setattr(lead_sync_service, "_find_lead_ids_for_contact_linked_to_event", lambda contact_id, item_id: [777])
        monkeypatch.setattr(lead_sync_service, "get_lead", lambda lead_id: {"ID": lead_id})

        stats = STATS()
        field_config = {"field_cpf_contact": "UF_CPF_CONTATO"}
        lead_sync_service._process_cliente_participant(
            [42], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, field_config, "", {}, [], item_id=28, force=False, event_already_happened=False, checked_in=False,
            cpf="05707711376",
        )

        contact_update_calls = [payload for m, payload in calls if m == "crm.contact.update"]
        assert len(contact_update_calls) == 1
        assert contact_update_calls[0]["fields"]["UF_CPF_CONTATO"] == "05707711376"

    def test_contato_com_cpf_ja_preenchido_nao_sobrescreve(self, monkeypatch):
        # Já vinculado ao item da SPA também, pra isolar: a única coisa que
        # poderia gerar um crm.contact.update aqui seria o CPF, e não deve.
        calls = []
        contact_data = {"ID": 42, "UF_CPF_CONTATO": "11122233344", lead_sync_service.FIELD_PARENT_ID_EVENTO_SPA: 28}
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: contact_data if method == "crm.contact.get" else calls.append((method, payload)) or {})
        monkeypatch.setattr(lead_sync_service, "_find_lead_ids_for_contact_linked_to_event", lambda contact_id, item_id: [777])
        monkeypatch.setattr(lead_sync_service, "get_lead", lambda lead_id: {"ID": lead_id})

        stats = STATS()
        field_config = {"field_cpf_contact": "UF_CPF_CONTATO"}
        lead_sync_service._process_cliente_participant(
            [42], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, field_config, "", {}, [], item_id=28, force=False, event_already_happened=False, checked_in=False,
            cpf="05707711376",
        )

        contact_update_calls = [payload for m, payload in calls if m == "crm.contact.update"]
        assert not contact_update_calls


class TestSyncOneEvent:
    """sync_one_event() usa get_all_events() (todo evento, passado ou
    futuro), não list_upcoming_events() — "Forçar campos" precisa
    funcionar em evento já passado (ver eventos_helper.py)."""

    def test_acha_evento_passado_via_get_all_events(self, monkeypatch):
        monkeypatch.setattr(
            lead_sync_service, "get_all_events",
            lambda: [{"id": "e_passado", "name": "Evento Passado", "start_date": "2020-01-01T10:00:00-03:00"}],
        )
        monkeypatch.setattr(
            lead_sync_service, "list_upcoming_events",
            lambda: (_ for _ in ()).throw(AssertionError("não deveria usar list_upcoming_events aqui")),
        )
        monkeypatch.setattr(lead_sync_service, "process_event", lambda event, stats, force=False: True)
        monkeypatch.setattr(lead_sync_service.logs_repo, "insert_execucao", lambda *a, **kw: None)

        result = lead_sync_service.sync_one_event("e_passado", force=True)
        assert result["event_id"] == "e_passado"
        assert result["changed"] is True

    def test_evento_nao_encontrado_levanta_erro(self, monkeypatch):
        monkeypatch.setattr(lead_sync_service, "get_all_events", lambda: [])
        try:
            lead_sync_service.sync_one_event("e_inexistente")
            assert False, "deveria ter levantado ValueError"
        except ValueError:
            pass


class TestSyncAllUpcomingEventsLock:
    """A trava 'global' substitui o `concurrency: group: automacao-a` que o
    GitHub Actions garantia sozinho — sem ela, o Cron Job Render (motor
    agendado) e o painel (sob demanda) poderiam sobrepor."""

    def test_trava_em_uso_pula_execucao_sem_erro(self, monkeypatch):
        def _raise(escopo, quem):
            raise lead_sync_service.SyncLockHeld("já travado")

        monkeypatch.setattr(lead_sync_service, "acquire_lock", _raise)
        monkeypatch.setattr(
            lead_sync_service, "list_upcoming_events",
            lambda: (_ for _ in ()).throw(AssertionError("não deveria nem buscar eventos")),
        )

        result = lead_sync_service.sync_all_upcoming_events()
        assert result == lead_sync_service._new_stats()

    def test_adquire_e_libera_a_trava_em_execucao_normal(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "acquire_lock", lambda escopo, quem: calls.append(("acquire", escopo, quem)))
        monkeypatch.setattr(lead_sync_service, "release_lock", lambda escopo: calls.append(("release", escopo)))
        monkeypatch.setattr(lead_sync_service, "list_upcoming_events", lambda: [])
        monkeypatch.setattr(lead_sync_service.logs_repo, "insert_execucao", lambda *a, **kw: None)

        lead_sync_service.sync_all_upcoming_events()

        assert calls == [("acquire", "global", "cron"), ("release", "global")]

    def test_libera_a_trava_mesmo_se_process_event_falhar(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "acquire_lock", lambda escopo, quem: None)
        monkeypatch.setattr(lead_sync_service, "release_lock", lambda escopo: calls.append(escopo))
        monkeypatch.setattr(lead_sync_service, "list_upcoming_events", lambda: [{"id": "e1"}])
        monkeypatch.setattr(lead_sync_service, "_filter_eventos_ativos", lambda events: events)
        monkeypatch.setattr(lead_sync_service, "process_event", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("bitrix fora do ar")))
        monkeypatch.setattr(lead_sync_service.logs_repo, "insert_execucao", lambda *a, **kw: None)

        try:
            lead_sync_service.sync_all_upcoming_events()
        except RuntimeError:
            pass

        assert calls == ["global"]


POS_EVENTO_FIELD_CONFIG = {"field_presente_no_evento": "UF_PRESENTE", "stage_pos_evento": "NEWPOSEVENTO"}


class TestAplicarPosEvento:
    """A Automação B foi aposentada — quem preenche "Presente no evento" e
    move o Lead pra "Pós Evento" agora é o botão "Forçar atualização de
    campos", via _aplicar_pos_evento."""

    def test_evento_passado_force_presente_seta_status_e_presenca(self, monkeypatch):
        monkeypatch.setattr(lead_sync_service, "resolve_enum_id", lambda field, valor: f"ID-{valor}")
        fields = {}
        lead_sync_service._aplicar_pos_evento(fields, "NEWINSCRITO", True, True, True, POS_EVENTO_FIELD_CONFIG)
        assert fields["STATUS_ID"] == "NEWPOSEVENTO"
        assert fields["UF_PRESENTE"] == "ID-Presente"

    def test_nao_presente_resolve_valor_nao_presente(self, monkeypatch):
        monkeypatch.setattr(lead_sync_service, "resolve_enum_id", lambda field, valor: f"ID-{valor}")
        fields = {}
        lead_sync_service._aplicar_pos_evento(fields, "NEWINSCRITO", True, True, False, POS_EVENTO_FIELD_CONFIG)
        assert fields["UF_PRESENTE"] == "ID-Não Presente"

    def test_lead_ganho_nao_mexe(self, monkeypatch):
        monkeypatch.setattr(lead_sync_service, "resolve_enum_id", lambda *a: (_ for _ in ()).throw(AssertionError("não deveria resolver enum")))
        fields = {}
        lead_sync_service._aplicar_pos_evento(fields, "CONVERTED", True, True, True, POS_EVENTO_FIELD_CONFIG)
        assert fields == {}

    def test_lead_perdido_nao_mexe(self):
        fields = {}
        lead_sync_service._aplicar_pos_evento(fields, "JUNK", True, True, True, POS_EVENTO_FIELD_CONFIG)
        assert fields == {}

    def test_sem_force_nao_mexe(self):
        fields = {}
        lead_sync_service._aplicar_pos_evento(fields, "NEWINSCRITO", True, False, True, POS_EVENTO_FIELD_CONFIG)
        assert fields == {}

    def test_evento_nao_passou_nao_mexe(self):
        fields = {}
        lead_sync_service._aplicar_pos_evento(fields, "NEWINSCRITO", False, True, True, POS_EVENTO_FIELD_CONFIG)
        assert fields == {}

    def test_sem_campo_presente_configurado_so_move_estagio(self):
        fields = {}
        field_config = {"field_presente_no_evento": "", "stage_pos_evento": "NEWPOSEVENTO"}
        lead_sync_service._aplicar_pos_evento(fields, "NEWINSCRITO", True, True, True, field_config)
        assert fields == {"STATUS_ID": "NEWPOSEVENTO"}


class TestContatoComLeadAbertoPosEvento:
    def test_evento_passado_force_move_pos_evento_mesmo_funil_antigo(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: calls.append((method, payload)) or {})
        monkeypatch.setattr(lead_sync_service, "get_lead", lambda lead_id: {"ID": lead_id, "STATUS_ID": "UC_Z0M384"})
        monkeypatch.setattr(lead_sync_service, "_find_lead_ids_for_contact_linked_to_event", lambda contact_id, item_id: [777])
        monkeypatch.setattr(lead_sync_service, "resolve_enum_id", lambda field, valor: f"ID-{valor}")

        stats = STATS()
        lead_sync_service._process_cliente_participant(
            [42], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, POS_EVENTO_FIELD_CONFIG, "", {}, [], item_id=28, force=True, event_already_happened=True, checked_in=True,
        )

        lead_update_calls = [payload for method, payload in calls if method == "crm.lead.update"]
        assert len(lead_update_calls) == 1
        assert lead_update_calls[0]["id"] == 777
        assert lead_update_calls[0]["fields"]["STATUS_ID"] == "NEWPOSEVENTO"
        assert lead_update_calls[0]["fields"]["UF_PRESENTE"] == "ID-Presente"
        assert stats["leads_atualizados"] == 1

    def test_evento_nao_passado_nao_mexe(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: calls.append((method, payload)) or {})
        monkeypatch.setattr(lead_sync_service, "get_lead", lambda lead_id: {"ID": lead_id, "STATUS_ID": "UC_Z0M384"})
        monkeypatch.setattr(lead_sync_service, "_find_lead_ids_for_contact_linked_to_event", lambda contact_id, item_id: [777])

        stats = STATS()
        lead_sync_service._process_cliente_participant(
            [42], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, POS_EVENTO_FIELD_CONFIG, "", {}, [], item_id=28, force=True, event_already_happened=False, checked_in=True,
        )

        # force=True ainda reenvia o vínculo com o item da SPA (comportamento
        # existente de "Forçar atualização de campos"), mas sem
        # event_already_happened a defesa de _aplicar_pos_evento não deve
        # colocar o Lead em "Pós Evento".
        lead_update_calls = [payload for method, payload in calls if method == "crm.lead.update"]
        assert len(lead_update_calls) == 1
        assert "STATUS_ID" not in lead_update_calls[0]["fields"]

    def test_lead_aberto_nao_vinculado_a_este_evento_nao_e_varrido_pro_pos_evento(self, monkeypatch):
        """Regressão: um Lead aberto do Contato em outra negociação (não
        vinculado a ESTE evento) nunca deve ser movido pra 'Pós Evento' por
        um force-rerun deste evento — só o Lead deste evento específico."""
        calls = []

        def fake_bitrix_call(method, payload):
            if method == "crm.contact.get":
                return {}
            calls.append((method, payload))
            return "123" if method == "crm.lead.add" else {}

        monkeypatch.setattr(lead_sync_service, "bitrix_call", fake_bitrix_call)
        monkeypatch.setattr(lead_sync_service, "resolve_enum_id", lambda field, valor: f"ID-{valor}")
        monkeypatch.setattr(lead_sync_service, "resolve_assessor_and_origem", lambda cupom: (None, "Inscrito Desconhecido"))
        # Nenhum Lead vinculado a este evento -> cria um novo (já nasce em
        # Pós Evento, ver TestCreateLeadFromParticipantPosEvento). O Lead
        # #777 de uma negociação paralela nunca é buscado nem tocado.
        monkeypatch.setattr(lead_sync_service, "_find_lead_ids_for_contact_linked_to_event", lambda contact_id, item_id: [])

        stats = STATS()
        field_config = {**POS_EVENTO_FIELD_CONFIG, "field_data_do_evento": "", "field_nome_do_evento": "", "field_sympla_event_id": "", "field_filtrar_evento": "", "field_origem": "", "stage_alvo": "NEWINSCRITO"}
        lead_sync_service._process_cliente_participant(
            [42], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, field_config, "", {}, [], item_id=28, force=True, event_already_happened=True, checked_in=True,
        )

        assert not any(method == "crm.lead.update" and payload.get("id") == 777 for method, payload in calls)
        add_payload = next(p for m, p in calls if m == "crm.lead.add")
        assert add_payload["fields"]["STATUS_ID"] == "NEWPOSEVENTO"


class TestCreateLeadFromParticipantPosEvento:
    def _base_field_config(self):
        return {
            "field_data_do_evento": "", "field_nome_do_evento": "", "field_sympla_event_id": "",
            "field_filtrar_evento": "", "field_origem": "", "stage_alvo": "NEWINSCRITO",
            "field_presente_no_evento": "UF_PRESENTE", "stage_pos_evento": "NEWPOSEVENTO",
        }

    def test_lead_novo_pra_evento_passado_ja_nasce_em_pos_evento(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: calls.append((method, payload)) or "123")
        monkeypatch.setattr(lead_sync_service, "resolve_assessor_and_origem", lambda cupom: (None, "Inscrito Desconhecido"))
        monkeypatch.setattr(lead_sync_service, "resolve_enum_id", lambda field, valor: f"ID-{valor}")

        stats = STATS()
        participant = {"id": "1", "first_name": "Fulano", "last_name": "Teste"}
        lead_sync_service.create_lead_from_participant(
            participant, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, self._base_field_config(), "", {}, [],
            event_already_happened=True, force=True, checked_in=False,
        )

        add_payload = next(p for m, p in calls if m == "crm.lead.add")
        assert add_payload["fields"]["STATUS_ID"] == "NEWPOSEVENTO"
        assert add_payload["fields"]["UF_PRESENTE"] == "ID-Não Presente"

    def test_lead_novo_pra_evento_futuro_fica_em_inscrito(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: calls.append((method, payload)) or "123")
        monkeypatch.setattr(lead_sync_service, "resolve_assessor_and_origem", lambda cupom: (None, "Inscrito Desconhecido"))

        stats = STATS()
        participant = {"id": "1", "first_name": "Fulano", "last_name": "Teste"}
        lead_sync_service.create_lead_from_participant(
            participant, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, self._base_field_config(), "", {}, [],
            event_already_happened=False, force=True, checked_in=False,
        )

        add_payload = next(p for m, p in calls if m == "crm.lead.add")
        assert add_payload["fields"]["STATUS_ID"] == "NEWINSCRITO"
        assert "UF_PRESENTE" not in add_payload["fields"]
