from services import duplicidade_service


def _lead(id_, name="", status="NEWLEAD", phone="+5585999998888"):
    return {"ID": str(id_), "NAME": name, "STATUS_ID": status, "PHONE": [{"VALUE": phone}] if phone else []}


class TestDetectarDuplicadosPorTelefone:
    def test_agrupa_por_telefone_normalizado_e_insere_candidato(self, monkeypatch):
        leads = [
            _lead(100, "Gabrielle Lima", phone="+5585988220472"),
            _lead(101, "Gabrielle Teixeira", phone="8588220472"),
            _lead(102, "Fulano Sem Duplicata", phone="+5585911112222"),
        ]
        monkeypatch.setattr(duplicidade_service, "bitrix_list_all", lambda method, payload: leads)
        monkeypatch.setattr(duplicidade_service.duplicados_repo, "existe_par", lambda a, b: False)
        inserted = []
        monkeypatch.setattr(duplicidade_service.duplicados_repo, "insert_candidato", lambda **kw: inserted.append(kw) or {})

        stats = duplicidade_service.detectar_duplicados_por_telefone()

        assert stats["leads_verificados"] == 3
        assert stats["grupos_com_duplicata"] == 1
        assert stats["candidatos_novos"] == 1
        assert len(inserted) == 1
        assert inserted[0]["lead_id_a"] == 100
        assert inserted[0]["lead_id_b"] == 101

    def test_par_ja_existente_nao_reinsere(self, monkeypatch):
        leads = [_lead(100, phone="+5585988220472"), _lead(101, phone="8588220472")]
        monkeypatch.setattr(duplicidade_service, "bitrix_list_all", lambda method, payload: leads)
        monkeypatch.setattr(duplicidade_service.duplicados_repo, "existe_par", lambda a, b: True)
        monkeypatch.setattr(
            duplicidade_service.duplicados_repo,
            "insert_candidato",
            lambda **kw: (_ for _ in ()).throw(AssertionError("não deveria inserir de novo")),
        )

        stats = duplicidade_service.detectar_duplicados_por_telefone()

        assert stats["candidatos_novos"] == 0

    def test_lead_sem_telefone_nao_forma_grupo(self, monkeypatch):
        leads = [_lead(100, phone=""), _lead(101, phone="")]
        monkeypatch.setattr(duplicidade_service, "bitrix_list_all", lambda method, payload: leads)

        stats = duplicidade_service.detectar_duplicados_por_telefone()

        assert stats["grupos_com_duplicata"] == 0


class TestExecutarMerge:
    def test_mescla_principal_por_vinculo_spa_e_apaga_secundario(self, monkeypatch):
        candidato = {"id": "1", "status": "pendente", "lead_id_a": 100, "lead_id_b": 101}
        monkeypatch.setattr(duplicidade_service.duplicados_repo, "get_by_id", lambda _id: candidato)

        lead_a = {"ID": "100", "NAME": "Gabrielle Lima", "EMAIL": [{"VALUE": "a@b.com"}]}
        lead_b = {"ID": "101", "NAME": "Gabrielle Teixeira", "PARENT_ID_1112": "28", "CONTACT_ID": "55"}

        def _get_lead(lead_id):
            return lead_a if int(lead_id) == 100 else lead_b

        monkeypatch.setattr(duplicidade_service, "get_lead", _get_lead)
        monkeypatch.setattr(duplicidade_service, "_contar_activities", lambda lead_id: [])

        calls = []
        monkeypatch.setattr(duplicidade_service, "bitrix_call", lambda method, payload: calls.append((method, payload)))

        status_calls = []
        monkeypatch.setattr(duplicidade_service.duplicados_repo, "set_status", lambda cid, status: status_calls.append((cid, status)))

        resultado = duplicidade_service.executar_merge("1")

        assert resultado == {"primary_id": 101, "secondary_id": 100}
        methods = [m for m, _ in calls]
        assert "crm.lead.delete" in methods
        delete_payload = next(p for m, p in calls if m == "crm.lead.delete")
        assert delete_payload["id"] == 100
        assert status_calls == [("1", "mesclado")]

    def test_candidato_ja_resolvido_levanta_erro(self, monkeypatch):
        candidato = {"id": "1", "status": "mesclado", "lead_id_a": 100, "lead_id_b": 101}
        monkeypatch.setattr(duplicidade_service.duplicados_repo, "get_by_id", lambda _id: candidato)

        try:
            duplicidade_service.executar_merge("1")
            assert False, "deveria ter levantado ValueError"
        except ValueError:
            pass

    def test_transfere_contact_id_do_secundario_pro_principal(self, monkeypatch):
        candidato = {"id": "1", "status": "pendente", "lead_id_a": 100, "lead_id_b": 101}
        monkeypatch.setattr(duplicidade_service.duplicados_repo, "get_by_id", lambda _id: candidato)

        lead_a = {"ID": "100", "NAME": "A", "PARENT_ID_1112": "28"}
        lead_b = {"ID": "101", "NAME": "B", "CONTACT_ID": "77"}

        def _get_lead(lead_id):
            return lead_a if int(lead_id) == 100 else lead_b

        monkeypatch.setattr(duplicidade_service, "get_lead", _get_lead)
        monkeypatch.setattr(duplicidade_service, "_contar_activities", lambda lead_id: [])
        monkeypatch.setattr(duplicidade_service.duplicados_repo, "set_status", lambda cid, status: None)

        calls = []
        monkeypatch.setattr(duplicidade_service, "bitrix_call", lambda method, payload: calls.append((method, payload)))

        duplicidade_service.executar_merge("1")

        update_payload = next(p for m, p in calls if m == "crm.lead.update")
        assert update_payload["id"] == 100
        assert update_payload["fields"]["CONTACT_ID"] == "77"
