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


PARTICIPANT = {"id": "999"}
STATS = lambda: {"eventos_processados": 0, "leads_criados": 0, "leads_atualizados": 0, "erros": 0}


class TestProcessClienteParticipant:
    def test_contato_sem_lead_aberto_cria_lead_novo(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: {} if method == "crm.contact.get" else calls.append((method, payload)))
        monkeypatch.setattr(lead_sync_service, "_find_open_lead_ids_for_contact", lambda contact_id: [])
        monkeypatch.setattr(lead_sync_service, "create_lead_from_participant", lambda *a, **kw: calls.append(("create_lead", kw)))

        stats = STATS()
        lead_sync_service._process_cliente_participant(
            [42], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, {}, "", {}, [], item_id=28, force=False,
        )

        assert any(m == "create_lead" for m, _ in calls)
        create_kwargs = next(kw for m, kw in calls if m == "create_lead")
        assert create_kwargs["contact_id"] == 42
        assert create_kwargs["item_id"] == 28

    def test_contato_com_lead_aberto_so_vincula_nao_cria(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: calls.append((method, payload)) or {})
        monkeypatch.setattr(lead_sync_service, "get_lead", lambda lead_id: {"ID": lead_id})
        monkeypatch.setattr(lead_sync_service, "_find_open_lead_ids_for_contact", lambda contact_id: [777])
        monkeypatch.setattr(lead_sync_service, "create_lead_from_participant", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("não deveria criar Lead novo")))

        stats = STATS()
        lead_sync_service._process_cliente_participant(
            [42], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, {}, "", {}, [], item_id=28, force=False,
        )

        lead_update_calls = [payload for method, payload in calls if method == "crm.lead.update"]
        assert len(lead_update_calls) == 1
        assert lead_update_calls[0]["id"] == 777
        assert lead_update_calls[0]["fields"] == {lead_sync_service.FIELD_PARENT_ID_EVENTO_SPA: 28}
        assert stats["leads_atualizados"] == 1

    def test_contato_ja_vinculado_ao_item_nao_reenvia(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: calls.append((method, payload)) or {lead_sync_service.FIELD_PARENT_ID_EVENTO_SPA: 28})
        monkeypatch.setattr(lead_sync_service, "_find_open_lead_ids_for_contact", lambda contact_id: [777])
        monkeypatch.setattr(lead_sync_service, "get_lead", lambda lead_id: {"ID": lead_id, lead_sync_service.FIELD_PARENT_ID_EVENTO_SPA: 28})

        stats = STATS()
        lead_sync_service._process_cliente_participant(
            [42], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, {}, "", {}, [], item_id=28, force=False,
        )

        assert not any(method == "crm.contact.update" for method, _ in calls)
        assert not any(method == "crm.lead.update" for method, _ in calls)

    def test_multiplos_contatos_usa_so_o_de_menor_id_e_loga_duplicado(self, monkeypatch):
        create_calls = []
        log_calls = []
        monkeypatch.setattr(lead_sync_service, "bitrix_call", lambda method, payload: {})
        monkeypatch.setattr(lead_sync_service, "_find_open_lead_ids_for_contact", lambda contact_id: [])
        monkeypatch.setattr(lead_sync_service, "create_lead_from_participant", lambda *a, **kw: create_calls.append(kw))
        monkeypatch.setattr(lead_sync_service.logs_repo, "insert_item", lambda *a, **kw: log_calls.append((a, kw)))

        stats = STATS()
        lead_sync_service._process_cliente_participant(
            [25216, 538], PARTICIPANT, "+5585999998888", "a@b.com", "Evento", "2026-01-01", "e1", "",
            stats, {}, "", {}, [], item_id=28, force=False,
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
        monkeypatch.setattr(lead_sync_service, "find_matching_contact_ids", lambda phone, email: ([42], "telefone"))
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
        monkeypatch.setattr(lead_sync_service, "find_matching_contact_ids", lambda phone, email: ([], None))
        monkeypatch.setattr(lead_sync_service, "find_matching_lead_ids", lambda *a, **kw: ([], None))

        stats = STATS()
        field_config = {"field_data_do_evento": "", "field_nome_do_evento": "", "field_sympla_event_id": "", "field_filtrar_evento": "", "field_origem": "", "stage_alvo": ""}
        result = lead_sync_service.process_participant(
            {"id": "1", "email": ""}, "Evento", "2026-01-01", "e1", "", lambda: {}, stats, field_config, [],
        )
        assert result is True  # sem telefone/e-mail/nome batendo -> pulado, mas tratado como sucesso


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
