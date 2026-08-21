"""
O motor da Automação A: descobre eventos próximos na Sympla, casa cada
inscrito com um Lead do Bitrix24 (CPF → telefone → e-mail → nome), avança
o estágio quando aplicável ou cria um Lead novo, resolvendo cupom→assessor
via services/coupon_service.py.

Extraído de automacao_a_inscricoes.py (que virou um wrapper de CLI fino
por cima daqui) pra ter DOIS pontos de entrada usados igualmente pelo
Cron Job agendado e pelo painel administrativo:
- sync_all_upcoming_events(): o fluxo de sempre, todos os eventos futuros.
- sync_one_event(event_id, force=False): um evento só, sob demanda
  ("Sincronizar agora"/"Forçar atualização de campos" no painel).

Só chama a API do Bitrix quando há inscrito NOVO desde a última execução
— a tabela participantes_processados (Supabase) guarda quem já foi
processado por evento, então rodar sem nenhuma inscrição nova não gera
nenhuma chamada ao Bitrix.

É idempotente: só escreve os campos que realmente mudaram, então pode
rodar quantas vezes quiser.
"""

import logging
import time
from datetime import date, datetime, timezone

from common import (
    bitrix_call,
    bitrix_list_all,
    build_cupom_by_order_id,
    ensure_enum_value,
    extract_cpf,
    extract_discount_code,
    find_contact_ids_by_cpf,
    find_contact_ids_by_email,
    find_contact_ids_by_phone,
    find_lead_ids_by_cpf,
    find_lead_ids_by_email,
    find_lead_ids_by_phone,
    format_event_label,
    format_phone_br,
    extract_phone,
    get_all_events,
    get_lead,
    get_sympla_all_orders,
    get_sympla_all_participants,
    list_upcoming_events,
    normalize_cpf,
    normalize_email,
    normalize_name,
    participant_full_name,
    resolve_enum_id,
    resolve_user_id_by_email,
    spa_add_item,
    spa_find_item_by_sympla_event_id,
    spa_update_item,
    FIELD_PARENT_ID_EVENTO_SPA,
    FIELD_SPA_NOME_EVENTO,
    FIELD_SPA_SYMPLA_EVENT_ID,
    FIELD_SPA_TOTAL_FALTOSOS,
    FIELD_SPA_TOTAL_INSCRITOS,
    FIELD_SPA_TOTAL_PRESENTES,
    FIELD_SPA_ULTIMA_SINCRONIZACAO,
    LEAD_CLOSED_STAGES,
    OLD_FUNNEL_STAGES,
    VALOR_NAO_PRESENTE,
    VALOR_PRESENTE,
)
from domain.campo_extra_mapeamento import resolve_extra_fields
from domain.matching import (
    choose_primary_contact_id,
    contact_needs_new_event_lead,
    find_matching_contact_ids as _find_matching_contact_ids,
    find_matching_lead_ids as _find_matching_lead_ids,
    names_are_compatible,
)
from domain.stage_rules import build_fields_to_advance, deve_mover_pos_evento
from repositories import eventos_config_repo, logs_repo, processed_repo
from repositories.sync_locks_repo import SyncLockHeld, acquire_lock, release_lock
from services import campo_mapeamento_service, config_service
from services.coupon_service import resolve_assessor_and_origem

log = logging.getLogger("services.lead_sync_service")


def _new_stats() -> dict:
    return {"eventos_processados": 0, "leads_criados": 0, "leads_atualizados": 0, "erros": 0}


def _resolve_field_config() -> dict:
    """Resolve os códigos de campo/estágio via services/config_service.py
    (tabela config_kv, com fallback pro .env) — uma vez por evento
    processado, não uma vez por participante (o serviço já cacheia por 60s,
    isso só evita repetir o dict a cada chamada)."""
    return {
        "field_data_do_evento": config_service.get_field_data_do_evento(),
        "field_nome_do_evento": config_service.get_field_nome_do_evento(),
        "field_sympla_event_id": config_service.get_field_sympla_event_id(),
        "field_filtrar_evento": config_service.get_field_filtrar_evento(),
        "field_origem": config_service.get_field_origem(),
        "field_presente_no_evento": config_service.get_field_presente_no_evento(),
        "field_cpf_lead": config_service.get_field_cpf_lead(),
        "field_cpf_contact": config_service.get_field_cpf_contact(),
        "stage_alvo": config_service.get_stage_inscrito_pro_evento(),
        "stage_pos_evento": config_service.get_stage_pos_evento(),
    }


# ---------------------------------------------------------------------------
# Fallback por nome: busca só os Leads cujo NAME contém o nome do inscrito
# (filtro "%NAME" do Bitrix) em vez de baixar o portal inteiro — o portal
# tem milhares de Leads, então indexar tudo em memória a cada fallback
# seria caro demais. A comparação final ainda é feita localmente com
# names_are_compatible (palavra inteira, não igualdade exata — "Kelly
# Sabina" confirma contra "KELLY SABINA PASSOS SANTOS"), o filtro do
# Bitrix só reduz a lista de candidatos.
# ---------------------------------------------------------------------------
def find_lead_ids_by_name(full_name: str) -> list[int]:
    if not normalize_name(full_name):
        return []
    candidates = bitrix_list_all(
        "crm.lead.list",
        {"filter": {"%NAME": full_name}, "select": ["ID", "NAME"]},
    )
    return [int(lead["ID"]) for lead in candidates if names_are_compatible(full_name, lead.get("NAME", ""))]


def find_matching_lead_ids(cpf: str, phone_key: str, email: str, full_name: str) -> tuple[list[int], str | None]:
    """Fina casca sobre domain.matching: liga a cascata de decisão (pura)
    às buscas reais no Bitrix. Mantida com esta assinatura porque
    preview_novos_leads.py importa esta função diretamente deste módulo.
    O código do campo de CPF é resolvido aqui via config_service (cache
    de 60s) em vez de vir por parâmetro — diferente de telefone/e-mail
    (busca nativa do Bitrix), CPF é campo customizado configurável."""
    return _find_matching_lead_ids(
        cpf,
        phone_key,
        email,
        full_name,
        lookup_by_cpf=lambda c: find_lead_ids_by_cpf(c, config_service.get_field_cpf_lead()),
        lookup_by_phone=find_lead_ids_by_phone,
        lookup_by_email=find_lead_ids_by_email,
        lookup_by_name=find_lead_ids_by_name,
        get_lead_name=lambda lead_id: (get_lead(lead_id) or {}).get("NAME", ""),
    )


def find_matching_contact_ids(cpf: str, phone_key: str, email: str) -> tuple[list[int], str | None]:
    """Fina casca sobre domain.matching para Contatos (clientes) — CPF,
    telefone e e-mail, sem fallback por nome (ver domain/matching.py)."""
    return _find_matching_contact_ids(
        cpf,
        phone_key,
        email,
        lookup_by_cpf=lambda c: find_contact_ids_by_cpf(c, config_service.get_field_cpf_contact()),
        lookup_by_phone=find_contact_ids_by_phone,
        lookup_by_email=find_contact_ids_by_email,
    )


def _already_linked_to_item(entity: dict, item_id: int) -> bool:
    """Bitrix guarda PARENT_ID_1112 como string (ex: "28"), não int —
    compara normalizado, senão o diff-check acha diferença toda vez e
    reenvia o campo numa rodada que não precisava."""
    return str(entity.get(FIELD_PARENT_ID_EVENTO_SPA)) == str(item_id)


def _find_open_lead_ids_for_contact(contact_id: int) -> list[int]:
    leads = bitrix_list_all("crm.lead.list", {"filter": {"CONTACT_ID": contact_id}, "select": ["ID", "STATUS_ID"]})
    return [int(lead["ID"]) for lead in leads if lead.get("STATUS_ID") not in LEAD_CLOSED_STAGES]


def _find_lead_ids_for_contact_linked_to_event(contact_id: int, item_id: int) -> list[int]:
    """Leads do Contato já vinculados a ESTE evento (item da SPA) — usado
    pra decidir se a inscrição já gerou um Lead antes (idempotência sob
    "Forçar atualização de campos", que reprocessa todo mundo). Não
    exclui LEAD_CLOSED_STAGES de propósito: mesmo que o Lead do evento já
    tenha sido fechado (Ganho/Perdido) numa rodada anterior, um rerun não
    deve criar um segundo Lead pra mesma inscrição."""
    leads = bitrix_list_all(
        "crm.lead.list",
        {"filter": {"CONTACT_ID": contact_id, FIELD_PARENT_ID_EVENTO_SPA: item_id}, "select": ["ID"]},
    )
    return [int(lead["ID"]) for lead in leads]


def _find_or_create_evento_item(sympla_event_id: str, event_name: str, event_date: str, inscritos_count: int, presentes_count: int) -> int | None:
    """Acha (ou cria) o item da SPA nativa "Eventos Sympla" pra esse
    evento, e atualiza os campos agregados (Total de Inscritos/Presentes/
    Faltosos, Última Sincronização, Nome do Evento). Fail-ABERTO: se
    qualquer chamada falhar, loga e retorna None — a sincronização de
    Lead/Contato continua normalmente, só sem o vínculo com a SPA nesta
    rodada (tentará de novo na próxima).

    Nunca mexe em stageId (a coluna Kanban do item) — isso é decisão
    humana/comercial, mesmo espírito da defesa que já existe pra nunca
    promover sozinho um Lead de funil antigo."""
    stat_fields = {
        FIELD_SPA_TOTAL_INSCRITOS: inscritos_count,
        FIELD_SPA_TOTAL_PRESENTES: presentes_count,
        FIELD_SPA_TOTAL_FALTOSOS: inscritos_count - presentes_count,
        FIELD_SPA_ULTIMA_SINCRONIZACAO: datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        FIELD_SPA_NOME_EVENTO: event_name,
    }
    try:
        item = spa_find_item_by_sympla_event_id(sympla_event_id)
        if item is None:
            item_id = spa_add_item({
                "title": f"{event_name} ({event_date})" if event_date else event_name,
                FIELD_SPA_SYMPLA_EVENT_ID: sympla_event_id,
                **stat_fields,
            })
            log.info("Item novo criado na SPA Eventos Sympla pro evento %s (id interno %s): item %s.", event_name, sympla_event_id, item_id)
        else:
            item_id = int(item["id"])
            spa_update_item(item_id, stat_fields)
        return item_id
    except Exception as exc:
        log.warning("Falha ao achar/criar item da SPA Eventos Sympla pra %s (id interno %s): %s", event_name, sympla_event_id, exc)
        return None


def build_cupom_map_loader(event_id: str):
    """Closure memoizado: só busca /orders da Sympla se algum participante
    novo realmente precisar (nenhum campo direto de cupom disponível)."""
    cache: dict[str, dict[str, str]] = {}

    def get() -> dict[str, str]:
        if "map" not in cache:
            cache["map"] = build_cupom_by_order_id(get_sympla_all_orders(event_id))
        return cache["map"]

    return get


def _aplicar_pos_evento(fields: dict, status_atual: str | None, event_already_happened: bool, force: bool, checked_in: bool, field_config: dict) -> None:
    """Mutação em `fields` (in place): se deve_mover_pos_evento() disser que
    sim, adiciona STATUS_ID=stage_pos_evento e, se o campo estiver
    configurado, "Presente no evento" (Presente/Não Presente conforme
    check-in real da Sympla) — substitui a Automação B (aposentada), que
    fazia isso reagindo a um robô nativo do Bitrix que não existe mais.

    Fica em lead_sync_service.py (não em domain/stage_rules.py, que só tem
    deve_mover_pos_evento) porque resolve_enum_id faz chamada de rede —
    domain/ é sempre puro."""
    if not deve_mover_pos_evento(status_atual, event_already_happened, force):
        return
    fields["STATUS_ID"] = field_config["stage_pos_evento"]
    if field_config["field_presente_no_evento"]:
        valor_texto = VALOR_PRESENTE if checked_in else VALOR_NAO_PRESENTE
        fields[field_config["field_presente_no_evento"]] = resolve_enum_id(field_config["field_presente_no_evento"], valor_texto)


def create_lead_from_participant(participant: dict, phone_raw: str, email: str, event_name: str, event_date: str, sympla_event_id: str, filtrar_evento_id: str, stats: dict, field_config: dict, cupom: str, valores_disponiveis: dict, extra_mapeamentos: list[dict], contact_id: int | None = None, item_id: int | None = None, event_already_happened: bool = False, force: bool = False, checked_in: bool = False, cpf: str = "") -> int:
    """Cria um Lead novo. contact_id/item_id são usados no branch "cliente"
    (Contato já existente que ainda não tem Lead vinculado a este evento):
    mesma lógica de cupom→assessor/origem de sempre também se aplica aqui —
    decisão confirmada com o usuário, um cliente que se inscreve com cupom
    de um assessor ainda deve gerar essa atribuição. Retorna o ID do Lead
    criado.

    event_already_happened/force/checked_in: se o evento já passou e é uma
    sincronização forçada, o Lead já nasce em "Pós Evento" com presença
    preenchida em vez de passar primeiro por "Inscrito Pro Evento" (ver
    _aplicar_pos_evento) — não faz sentido fingir que o evento ainda vai
    acontecer pra um Lead criado hoje sobre um evento do passado."""
    name = participant_full_name(participant)
    assessor_email, origem_valor = resolve_assessor_and_origem(cupom)

    fields = {
        "NAME": name or "Inscrito Sympla",
        "TITLE": name or "Inscrito Sympla",
        "PHONE": [{"VALUE": format_phone_br(phone_raw), "VALUE_TYPE": "WORK"}],
        "STATUS_ID": field_config["stage_alvo"],
    }
    if field_config["field_data_do_evento"]:
        fields[field_config["field_data_do_evento"]] = event_date
    if field_config["field_nome_do_evento"]:
        fields[field_config["field_nome_do_evento"]] = event_name
    if field_config["field_sympla_event_id"]:
        fields[field_config["field_sympla_event_id"]] = sympla_event_id
    if field_config["field_filtrar_evento"] and filtrar_evento_id:
        fields[field_config["field_filtrar_evento"]] = filtrar_evento_id
    if field_config["field_origem"]:
        fields[field_config["field_origem"]] = resolve_enum_id(field_config["field_origem"], origem_valor)
    if assessor_email:
        fields["ASSIGNED_BY_ID"] = resolve_user_id_by_email(assessor_email)
    if email:
        fields["EMAIL"] = [{"VALUE": normalize_email(email), "VALUE_TYPE": "WORK"}]
    if contact_id:
        fields["CONTACT_ID"] = contact_id
    if item_id:
        fields[FIELD_PARENT_ID_EVENTO_SPA] = item_id
    if cpf and field_config.get("field_cpf_lead"):
        fields[field_config["field_cpf_lead"]] = cpf
    fields.update(resolve_extra_fields(valores_disponiveis, extra_mapeamentos, lead=None))
    _aplicar_pos_evento(fields, None, event_already_happened, force, checked_in, field_config)

    new_id = bitrix_call("crm.lead.add", {"fields": fields})
    stats["leads_criados"] += 1
    responsavel_info = f", responsável={assessor_email}" if assessor_email else ""
    log.info("Novo lead %s criado pro participante %s (%s) — origem=%s%s.", new_id, participant.get("id"), name, origem_valor, responsavel_info)
    return int(new_id)


def _process_cliente_participant(contact_ids: list[int], participant: dict, phone_raw: str, email: str, event_name: str, event_date: str, event_id: str, filtrar_evento_id: str, stats: dict, field_config: dict, cupom: str, valores_disponiveis: dict, extra_mapeamentos: list[dict], item_id: int | None, force: bool, event_already_happened: bool, checked_in: bool, cpf: str = "") -> dict:
    """Branch "cliente": o inscrito bateu com um Contato já existente.
    Vincula o Contato ao item do evento (e preenche o CPF do Contato se
    estiver vazio — nunca sobrescreve um valor já preenchido); se esse
    Contato ainda não tem nenhum Lead vinculado a ESTE evento, cria um
    Lead novo em "Inscrito Pro Evento" (mesma lógica de cupom→assessor de
    sempre) — mesmo que o Contato já tenha outro Lead aberto em outro
    estágio (negociação em andamento, funil antigo etc.): esse Lead
    paralelo nunca é tocado, regra de negócio confirmada é que todo
    cliente inscrito precisa aparecer com card próprio em Inscrito Pro
    Evento. Se o Lead deste evento já existe (rerun via "Forçar
    atualização de campos"), só atualiza/vincula esse(s) Lead(s) — não
    cria de novo.

    Se bater com MAIS de um Contato (dado duplicado pré-existente no
    Bitrix — mesmo e-mail/telefone em dois registros — não causado pela
    automação), processa só o de ID mais baixo (domain.matching::
    choose_primary_contact_id) e REGISTRA o duplicado em
    execucoes_log_itens pra revisão/mesclagem manual, em vez de criar um
    Lead por Contato duplicado. Mesclar Contatos de verdade é uma tarefa
    separada — mexe em dado real de cliente (histórico de negociação,
    atividades), risco maior do que qualquer coisa que a automação já faz.

    Retorna o resultado do match pra process_participant persistir junto
    da marca de idempotência (participantes_processados, migração 0006):
    {"contact_id", "lead_id", "contact_ids_duplicados", "criou_lead",
    "atualizou"}. O laço `for contact_id in contact_ids` sempre roda
    exatamente uma vez chegando aqui (a lista já vem colapsada num
    Contato só, ou já tinha um só) — mantido como laço só pra minimizar o
    diff, não porque itere de verdade."""
    duplicados = list(contact_ids) if len(contact_ids) > 1 else None
    if len(contact_ids) > 1:
        primary_id = choose_primary_contact_id(contact_ids)
        log.warning(
            "Inscrito %s bateu com %d Contatos diferentes (dado duplicado no Bitrix, não criado pela automação): %s — usando o Contato %s (menor ID), demais ignorados.",
            participant.get("id"), len(contact_ids), contact_ids, primary_id,
        )
        logs_repo.insert_item(
            "CONTATO_DUPLICADO", "participante", f"participant #{participant.get('id')}", "ok", 0,
            sympla_event_id=event_id,
            detalhes={"contact_ids": contact_ids, "contact_id_usado": primary_id},
        )
        contact_ids = [primary_id]

    contact_id_usado = lead_id_usado = None
    criou_lead = atualizou = False

    for contact_id in contact_ids:
        contact_id_usado = contact_id
        contact = bitrix_call("crm.contact.get", {"id": contact_id})
        contact_fields = {}
        if item_id and (force or not _already_linked_to_item(contact, item_id)):
            contact_fields[FIELD_PARENT_ID_EVENTO_SPA] = item_id
        if cpf and field_config.get("field_cpf_contact") and not contact.get(field_config["field_cpf_contact"]):
            contact_fields[field_config["field_cpf_contact"]] = cpf
        if contact_fields:
            bitrix_call("crm.contact.update", {"id": contact_id, "fields": contact_fields})
            log.info("Contato %s atualizado (evento %s, item %s): %s", contact_id, event_name, item_id, contact_fields)

        existing_event_lead_ids = _find_lead_ids_for_contact_linked_to_event(contact_id, item_id) if item_id else []
        if contact_needs_new_event_lead(existing_event_lead_ids):
            lead_id_usado = create_lead_from_participant(
                participant, phone_raw, email, event_name, event_date, event_id, filtrar_evento_id,
                stats, field_config, cupom, valores_disponiveis, extra_mapeamentos,
                contact_id=contact_id, item_id=item_id,
                event_already_happened=event_already_happened, force=force, checked_in=checked_in, cpf=cpf,
            )
            criou_lead = True
        else:
            for lead_id in existing_event_lead_ids:
                lead = get_lead(lead_id)
                fields = {}
                if item_id and (force or not _already_linked_to_item(lead, item_id)):
                    fields[FIELD_PARENT_ID_EVENTO_SPA] = item_id
                _aplicar_pos_evento(fields, lead.get("STATUS_ID"), event_already_happened, force, checked_in, field_config)
                if fields:
                    bitrix_call("crm.lead.update", {"id": lead_id, "fields": fields})
                    stats["leads_atualizados"] += 1
                    atualizou = True
                    log.info("Lead %s (cliente, Lead do evento já existia) atualizado (evento %s, item %s): %s", lead_id, event_name, item_id, fields)
                lead_id_usado = lead_id

    return {
        "contact_id": contact_id_usado,
        "lead_id": lead_id_usado,
        "contact_ids_duplicados": duplicados,
        "criou_lead": criou_lead,
        "atualizou": atualizou,
    }


def process_participant(participant: dict, event_name: str, event_date: str, event_id: str, filtrar_evento_id: str, get_cupom_map, stats: dict, field_config: dict, extra_mapeamentos: list[dict], item_id: int | None = None, force: bool = False, event_already_happened: bool = False) -> dict | None:
    """Retorna um dict-resultado se o inscrito foi tratado com sucesso
    (atualizado, criado, ou legitimamente pulado — funil antigo/sem
    telefone), None se algo deu errado e precisa ser tentado de novo na
    próxima execução. Só entra na marca de "já processado" quem retorna
    não-None — assim uma falha transitória (permissão, campo faltando,
    rede) nunca faz a gente perder o inscrito pra sempre.

    O dict retornado (consumido por process_event -> processed_repo.
    mark_processed_batch, migração 0006) tem sempre as mesmas chaves:
    participant_id, is_cliente, match_method, bitrix_contact_id,
    bitrix_lead_id, contact_ids_duplicados — é o resultado do match que
    alimenta a aba Inscritos do painel. NÃO é gravado inline aqui (só
    retornado): gravar antes de saber se a chamada ao Bitrix teve sucesso
    quebraria a garantia de idempotência de participantes_processados
    (linha existe = nunca mais mexe nesse inscrito) — ver process_event.

    force=True ("Forçar atualização de campos" no painel) reenvia os campos
    de evento mesmo que já estejam iguais — não afeta a lógica normal de
    STATUS_ID nem a defesa de funil antigo, só os campos de data/nome/id do
    evento. A ÚNICA exceção é quando o evento já passou (event_already_happened):
    aí, force=True TAMBÉM move o Lead pra "Pós Evento" com "Presente no
    evento" preenchido, mesmo os de funil antigo — ver
    domain/stage_rules.py::deve_mover_pos_evento e _aplicar_pos_evento.

    item_id (id do item na SPA "Eventos Sympla") é resolvido uma vez por
    evento em process_event() — pode ser None se a SPA estiver indisponível
    (fail-aberto), nesse caso simplesmente não vincula nada à SPA nesta
    rodada, sem afetar a sincronização de Lead/Contato de verdade.

    Roda a cascata de Contato (cliente) ANTES da cascata de Lead
    (prospect) — ver domain/matching.py::find_matching_contact_ids.

    Grava um log por inscrito em execucoes_log_itens (PARTICIPANT_CREATED/
    UPDATED/SKIPPED — aba Logs do painel, filtro "Participante"), melhor
    esforço via _log_participante, mesmo espírito do _log_item de
    process_event um nível abaixo (grão por inscrito, não por evento)."""
    inicio = time.monotonic()

    def _log_participante(acao: str, status: str = "ok", erro: str | None = None, detalhes: dict | None = None) -> None:
        logs_repo.insert_item(
            acao, "participante", f"participant #{participant.get('id')}", status,
            int((time.monotonic() - inicio) * 1000),
            sympla_event_id=event_id, erro=erro, detalhes=detalhes,
        )

    def _resultado(acao: str, is_cliente: bool, match_method: str | None, contact_id: int | None = None, lead_id: int | None = None, duplicados: list[int] | None = None) -> dict:
        _log_participante(acao, detalhes={"is_cliente": is_cliente, "match_method": match_method, "contact_id": contact_id, "lead_id": lead_id})
        return {
            "participant_id": str(participant.get("id")),
            "is_cliente": is_cliente,
            "match_method": match_method,
            "bitrix_contact_id": contact_id,
            "bitrix_lead_id": lead_id,
            "contact_ids_duplicados": duplicados,
        }

    phone_raw = extract_phone(participant)
    phone_key = format_phone_br(phone_raw)
    email = participant.get("email") or ""
    full_name = participant_full_name(participant)
    cupom = extract_discount_code(participant, get_cupom_map)
    checked_in = bool((participant.get("checkin") or {}).get("check_in_date"))
    cpf_raw = extract_cpf(participant)
    cpf = normalize_cpf(cpf_raw)
    valores_disponiveis = {
        "cupom_desconto": cupom,
        "telefone": phone_key,
        "nome_completo": full_name,
        "email": email,
        "cpf": cpf_raw,
    }

    try:
        contact_ids, contact_match_method = find_matching_contact_ids(cpf, phone_key, email)
    except Exception as exc:
        log.error("Falha ao buscar contato (cliente) pro inscrito %s: %s", participant.get("id"), exc)
        stats["erros"] += 1
        _log_participante("PARTICIPANT_SKIPPED", status="error", erro=str(exc))
        return None

    if contact_ids:
        try:
            resultado_cliente = _process_cliente_participant(contact_ids, participant, phone_raw, email, event_name, event_date, event_id, filtrar_evento_id, stats, field_config, cupom, valores_disponiveis, extra_mapeamentos, item_id, force, event_already_happened, checked_in, cpf=cpf)
        except Exception as exc:
            log.error("Falha ao processar cliente (contato) pro inscrito %s: %s", participant.get("id"), exc)
            stats["erros"] += 1
            _log_participante("PARTICIPANT_SKIPPED", status="error", erro=str(exc))
            return None
        acao = "PARTICIPANT_CREATED" if resultado_cliente["criou_lead"] else ("PARTICIPANT_UPDATED" if resultado_cliente["atualizou"] else "PARTICIPANT_SKIPPED")
        return _resultado(
            acao, True, contact_match_method,
            contact_id=resultado_cliente["contact_id"], lead_id=resultado_cliente["lead_id"],
            duplicados=resultado_cliente["contact_ids_duplicados"],
        )

    try:
        lead_ids, match_method = find_matching_lead_ids(cpf, phone_key, email, full_name)
    except Exception as exc:
        log.error("Falha ao buscar lead pro inscrito %s: %s", participant.get("id"), exc)
        stats["erros"] += 1
        _log_participante("PARTICIPANT_SKIPPED", status="error", erro=str(exc))
        return None

    try:
        leads_by_id = {lead_id: get_lead(lead_id) for lead_id in lead_ids}
        open_lead_ids = [lid for lid in lead_ids if leads_by_id[lid].get("STATUS_ID") not in LEAD_CLOSED_STAGES]
        closed_lead_ids = [lid for lid in lead_ids if lid not in open_lead_ids]
        if closed_lead_ids:
            log.info("Lead(s) %s (fechado — JUNK/CONVERTED) ignorado(s) pro inscrito %s — não reabre sozinho.", closed_lead_ids, participant.get("id"))

        if open_lead_ids:
            lead_id_usado = open_lead_ids[0]
            atualizou = False
            for lead_id in open_lead_ids:
                lead = leads_by_id[lead_id]
                is_old_funnel = lead.get("STATUS_ID") in OLD_FUNNEL_STAGES
                fields = build_fields_to_advance(
                    lead, event_name, event_date, event_id, filtrar_evento_id, force=force,
                    field_data_do_evento=field_config["field_data_do_evento"],
                    field_nome_do_evento=field_config["field_nome_do_evento"],
                    field_sympla_event_id=field_config["field_sympla_event_id"],
                    field_filtrar_evento=field_config["field_filtrar_evento"],
                    stage_alvo=field_config["stage_alvo"],
                )
                if is_old_funnel:
                    # Defesa explícita: funil antigo pode ganhar os campos
                    # do evento (visibilidade de que se inscreveu de novo),
                    # mas o estágio nunca muda — mesmo que build_fields_to_advance
                    # mude de regra no futuro. _aplicar_pos_evento (abaixo) é
                    # a ÚNICA exceção deliberada a essa defesa.
                    fields.pop("STATUS_ID", None)
                fields.update(resolve_extra_fields(valores_disponiveis, extra_mapeamentos, lead=lead, force=force))
                if item_id and (force or not _already_linked_to_item(lead, item_id)):
                    fields[FIELD_PARENT_ID_EVENTO_SPA] = item_id
                if cpf and field_config.get("field_cpf_lead") and not lead.get(field_config["field_cpf_lead"]):
                    fields[field_config["field_cpf_lead"]] = cpf
                _aplicar_pos_evento(fields, lead.get("STATUS_ID"), event_already_happened, force, checked_in, field_config)
                if fields:
                    bitrix_call("crm.lead.update", {"id": lead_id, "fields": fields})
                    stats["leads_atualizados"] += 1
                    atualizou = True
                    lead_id_usado = lead_id
                    tag = " (funil antigo, só campos de evento)" if is_old_funnel else ""
                    log.info("Lead %s atualizado (match por %s)%s: %s", lead_id, match_method, tag, fields)
                else:
                    log.info("Lead %s já estava em dia, nada pra atualizar.", lead_id)
            acao = "PARTICIPANT_UPDATED" if atualizou else "PARTICIPANT_SKIPPED"
            return _resultado(acao, False, match_method, lead_id=lead_id_usado)
        elif phone_key:
            novo_lead_id = create_lead_from_participant(
                participant, phone_raw, email, event_name, event_date, event_id, filtrar_evento_id, stats, field_config, cupom, valores_disponiveis, extra_mapeamentos, item_id=item_id,
                event_already_happened=event_already_happened, force=force, checked_in=checked_in, cpf=cpf,
            )
            return _resultado("PARTICIPANT_CREATED", False, match_method, lead_id=novo_lead_id)
        else:
            log.warning("Inscrito sem telefone e sem nome/e-mail/cpf batendo com Lead existente aberto, pulando: %s", participant.get("id"))
            return _resultado("PARTICIPANT_SKIPPED", False, None)
    except Exception as exc:
        log.error("Falha ao processar inscrito %s: %s", participant.get("id"), exc)
        stats["erros"] += 1
        _log_participante("PARTICIPANT_SKIPPED", status="error", erro=str(exc))
        return None


def get_event_or_raise(event_id: str) -> dict:
    """Acha um evento (passado ou futuro) na Sympla pelo id interno.
    get_all_events(), não list_upcoming_events(): um evento já passado
    continua valendo pra inspeção/ação manual pelo painel (ex: "Forçar
    campos" e o botão "Reprocessar" da aba Inscritos)."""
    event = next((e for e in get_all_events() if e["id"] == event_id), None)
    if event is None:
        raise ValueError(f"Evento {event_id} não encontrado na Sympla.")
    return event


def _preparar_contexto_evento(event_id: str, event_name: str, event_date: str) -> dict:
    """Tudo que process_participant precisa resolver UMA vez por evento
    (não por inscrito): códigos de campo, mapeamentos extras, o item da
    lista "Filtrar Evento" (garante via chamada ao Bitrix, ensure_enum_value)
    e o loader preguiçoso de cupom. Extraído de process_event pra que o
    reprocessamento de UM inscrito (aba Inscritos) monte exatamente o
    mesmo contexto, sem duplicar a lógica — divergir aqui faria o botão
    manual se comportar diferente do cron.

    Deliberadamente NÃO inclui item_id/presentes_count (SPA "Eventos
    Sympla" + eventos_config): em process_event, isso é resolvido antes
    da checagem de "tem inscrito novo?" e roda em TODO tick, mesmo sem
    nada pra processar (mantém os contadores do Dashboard atualizados) —
    misturar aqui faria process_event resolver field_config/filtrar_evento
    (que inclui uma chamada ao Bitrix via ensure_enum_value) mesmo quando
    não há nada novo, quebrando a otimização documentada no topo do
    módulo ("só chama a API do Bitrix quando há inscrito novo")."""
    field_config = _resolve_field_config()
    extra_mapeamentos = campo_mapeamento_service.load_mapeamentos()

    filtrar_evento_id = ""
    if field_config["field_filtrar_evento"]:
        label = format_event_label(event_name, event_date)
        try:
            filtrar_evento_id = ensure_enum_value(field_config["field_filtrar_evento"], label)
        except Exception as exc:
            log.error("Falha ao garantir item '%s' na lista do campo %s: %s", label, field_config["field_filtrar_evento"], exc)

    event_already_happened = bool(event_date) and event_date < date.today().isoformat()

    return {
        "field_config": field_config,
        "extra_mapeamentos": extra_mapeamentos,
        "filtrar_evento_id": filtrar_evento_id,
        "get_cupom_map": build_cupom_map_loader(event_id),
        "event_already_happened": event_already_happened,
    }


def process_event(event: dict, stats: dict, force: bool = False) -> bool:
    """Retorna True se algum participante foi processado com sucesso nesse
    evento. force=True processa TODOS os participantes do evento de novo,
    não só os novos desde a última vez (usado por "Forçar atualização de
    campos") — ainda assim idempotente, porque process_participant só
    reenvia campo que realmente mudou (ou todos, se force=True).

    Idempotência via participantes_processados (Supabase), fail-FECHADO:
    se a leitura de quem já foi processado falhar, o evento inteiro é
    pulado nesta rodada (conta como erro, tenta de novo na próxima
    execução) — nunca tratar "não consegui ler" como "ninguém processado
    ainda", ou o motor tentaria reprocessar tudo a cada rodada até o
    Supabase voltar.

    Cada chamada grava uma linha em execucoes_log_itens (aba Logs do
    painel) — melhor esforço, uma falha ao logar nunca bloqueia a
    sincronização de verdade.

    event_already_happened (evento já passou) é calculado uma vez aqui e
    repassado pra process_participant — junto com force=True, é o gatilho
    pra mover Leads pra "Pós Evento" com presença preenchida (ver
    domain/stage_rules.py::deve_mover_pos_evento)."""
    event_id = event["id"]
    event_name = event.get("name", "")
    event_date = (event.get("start_date") or "")[:10]  # YYYY-MM-DD
    event_already_happened = bool(event_date) and event_date < date.today().isoformat()
    acao = "EVENT_FIELDS_FORCED" if force else "EVENT_SYNCED"
    inicio = time.monotonic()

    def _log_item(status: str, erro: str | None = None) -> None:
        duracao_ms = int((time.monotonic() - inicio) * 1000)
        logs_repo.insert_item(acao, "evento", f"event #{event_id}", status, duracao_ms, sympla_event_id=event_id, erro=erro)

    participants = get_sympla_all_participants(event_id)
    presentes_count = sum(1 for p in participants if (p.get("checkin") or {}).get("check_in_date"))

    try:
        eventos_config_repo.upsert_sync_result(event_id, event_name, event_date, len(participants), presentes_count)
    except Exception as exc:
        # Só alimenta os contadores do Dashboard/aba Eventos — nunca deve
        # bloquear a sincronização de verdade no Bitrix.
        log.warning("Falha ao atualizar eventos_config de %s: %s", event_id, exc)

    # Item da SPA nativa "Eventos Sympla" do Bitrix — fail-aberto (None se
    # indisponível, process_participant simplesmente não vincula nada à
    # SPA nesta rodada).
    item_id = _find_or_create_evento_item(event_id, event_name, event_date, len(participants), presentes_count)

    if force:
        participants_to_process = participants
    else:
        try:
            seen_ids = processed_repo.get_processed_ids(event_id)
        except Exception as exc:
            log.error("Falha ao ler participantes_processados de %s (id interno %s), pulando evento nesta rodada: %s", event_name, event_id, exc)
            stats["erros"] += 1
            _log_item("error", erro=str(exc))
            return False
        participants_to_process = [p for p in participants if str(p.get("id")) not in seen_ids]

    if not participants_to_process:
        log.info("Nenhum inscrito novo em %s (id interno %s) — %d inscrito(s) já processado(s) antes.", event_name, event_id, len(participants))
        _log_item("ok")
        return False

    log.info("%d inscrito(s) a processar em %s (id interno %s) de %d no total.", len(participants_to_process), event_name, event_id, len(participants))

    ctx = _preparar_contexto_evento(event_id, event_name, event_date)

    resultados = []
    for participant in participants_to_process:
        resultado = process_participant(participant, event_name, event_date, event_id, ctx["filtrar_evento_id"], ctx["get_cupom_map"], stats, ctx["field_config"], ctx["extra_mapeamentos"], item_id=item_id, force=force, event_already_happened=event_already_happened)
        if resultado is not None:
            resultados.append(resultado)

    if not resultados:
        _log_item("ok")
        return False

    try:
        processed_repo.mark_processed_batch(event_id, resultados)
    except Exception as exc:
        # Os Leads já foram atualizados/criados no Bitrix com sucesso — só
        # a marca de idempotência (e o resultado do match) falhou em
        # gravar. Não perde o inscrito: na pior das hipóteses ele é
        # reprocessado (idempotente) na próxima execução.
        log.warning("Falha ao marcar %d participante(s) como processados em %s: %s", len(resultados), event_id, exc)

    _log_item("ok")
    return True


def _filter_eventos_ativos(events: list[dict]) -> list[dict]:
    """Remove eventos pausados (Ativo/Inativo) ou removidos ("Remover") na
    aba Eventos do painel. Fail-ABERTO: se a leitura de eventos_config
    falhar, trata todos os eventos como ativos — uma tabela de config fora
    do ar não pode parar a sincronização inteira."""
    try:
        config_by_event = {row["sympla_event_id"]: row for row in eventos_config_repo.get_all()}
    except Exception as exc:
        log.warning("Falha ao ler eventos_config (%s) — tratando todos os eventos como ativos.", exc)
        return events

    def _ativo(event_id: str) -> bool:
        row = config_by_event.get(event_id)
        if row is None:
            return True
        return bool(row.get("ativo", True)) and not row.get("removido_em")

    return [e for e in events if _ativo(e["id"])]


def sync_all_upcoming_events(test_event_ids: set[str] | None = None) -> dict:
    """Fluxo de sempre: todos os eventos futuros, só participantes novos
    desde a última execução. Usado pelo Cron Job agendado. Grava um resumo
    em execucoes_log ao final (melhor esforço — alimenta o Dashboard).

    Adquire a trava 'global' (sync_locks) antes de começar — sem isso, um
    Cron Job cuja execução atrasa (evento com muitos inscritos novos)
    corre o risco de sobrepor com a próxima execução agendada. Antes,
    quem garantia isso era só o `concurrency: group: automacao-a` do
    GitHub Actions; agora que o motor tem dois pontos de entrada (Cron Job
    + painel), precisa ser explícito. Se a trava já estiver em uso, pula
    esta execução sem erro — a próxima tentativa (10min depois) resolve."""
    try:
        acquire_lock("global", "cron")
    except SyncLockHeld as exc:
        log.warning("Execução agendada pulada, trava global em uso: %s", exc)
        return _new_stats()

    try:
        iniciado_em = datetime.now(timezone.utc)
        events = list_upcoming_events()
        log.info("%d evento(s) próximo(s) encontrado(s) na Sympla.", len(events))

        if test_event_ids:
            events = [e for e in events if e["id"] in test_event_ids]
            log.info("Modo teste ativo (TEST_EVENT_IDS) — restrito a %d evento(s): %s", len(events), sorted(test_event_ids))
        else:
            events = _filter_eventos_ativos(events)

        stats = _new_stats()
        status = "ok"
        try:
            for event in events:
                stats["eventos_processados"] += 1
                process_event(event, stats)
        except Exception:
            status = "error"
            raise
        finally:
            logs_repo.insert_execucao("A", iniciado_em, datetime.now(timezone.utc), status, stats)

        return stats
    finally:
        release_lock("global")


def sync_one_event(event_id: str, force: bool = False) -> dict:
    """Sincroniza um evento só, sob demanda — usado pelo painel
    ("Sincronizar agora" com force=False, "Forçar atualização de campos"
    com force=True). Também grava um resumo em execucoes_log, mesmo espírito
    de sync_all_upcoming_events().

    Usa get_event_or_raise() (todo evento do organizador, passado ou
    futuro), não list_upcoming_events() — diferente do Cron Job (que só
    processa eventos futuros), aqui é uma ação explícita do painel sobre
    um evento específico, e "Forçar campos" precisa funcionar em evento
    já passado (é exatamente quando ele preenche presença e move pra Pós
    Evento)."""
    iniciado_em = datetime.now(timezone.utc)
    event = get_event_or_raise(event_id)

    stats = _new_stats()
    stats["eventos_processados"] = 1
    status = "ok"
    try:
        changed = process_event(event, stats, force=force)
    except Exception:
        status = "error"
        raise
    finally:
        logs_repo.insert_execucao("A", iniciado_em, datetime.now(timezone.utc), status, stats)

    return {**stats, "event_id": event_id, "force": force, "changed": changed}
