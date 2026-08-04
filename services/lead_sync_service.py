"""
O motor da Automação A: descobre eventos próximos na Sympla, casa cada
inscrito com um Lead do Bitrix24 (telefone → e-mail → nome), avança o
estágio quando aplicável ou cria um Lead novo, resolvendo cupom→assessor
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
from datetime import datetime, timezone

from common import (
    bitrix_call,
    bitrix_list_all,
    build_cupom_by_order_id,
    ensure_enum_value,
    extract_discount_code,
    find_contact_ids_by_email,
    find_contact_ids_by_phone,
    find_lead_ids_by_email,
    find_lead_ids_by_phone,
    format_event_label,
    format_phone_br,
    extract_phone,
    get_lead,
    get_sympla_all_orders,
    get_sympla_all_participants,
    list_upcoming_events,
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
    OLD_FUNNEL_STAGES,
)
from domain.campo_extra_mapeamento import resolve_extra_fields
from domain.matching import (
    choose_primary_contact_id,
    contact_needs_new_lead,
    find_matching_contact_ids as _find_matching_contact_ids,
    find_matching_lead_ids as _find_matching_lead_ids,
)
from domain.stage_rules import build_fields_to_advance
from repositories import eventos_config_repo, logs_repo, processed_repo
from repositories.sync_locks_repo import SyncLockHeld, acquire_lock, release_lock
from services import campo_mapeamento_service, config_service
from services.coupon_service import resolve_assessor_and_origem

# Estágios "fechados" padrão do Bitrix — um Lead nesses estágios não conta
# como "aberto no funil" pra decidir se um cliente (Contato) precisa de um
# Lead novo representando o interesse no evento.
LEAD_CLOSED_STAGES = {"CONVERTED", "JUNK"}

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
        "stage_alvo": config_service.get_stage_inscrito_pro_evento(),
    }


# ---------------------------------------------------------------------------
# Fallback por nome: busca só os Leads cujo NAME contém o nome do inscrito
# (filtro "%NAME" do Bitrix) em vez de baixar o portal inteiro — o portal
# tem milhares de Leads, então indexar tudo em memória a cada fallback
# seria caro demais. A comparação final ainda é feita localmente com
# normalize_name (ignora acento/maiúscula/espaçamento), o filtro do Bitrix
# só reduz a lista de candidatos.
# ---------------------------------------------------------------------------
def find_lead_ids_by_name(full_name: str) -> list[int]:
    key = normalize_name(full_name)
    if not key:
        return []
    candidates = bitrix_list_all(
        "crm.lead.list",
        {"filter": {"%NAME": full_name}, "select": ["ID", "NAME"]},
    )
    return [int(lead["ID"]) for lead in candidates if normalize_name(lead.get("NAME", "")) == key]


def find_matching_lead_ids(phone_key: str, email: str, full_name: str) -> tuple[list[int], str | None]:
    """Fina casca sobre domain.matching: liga a cascata de decisão (pura)
    às buscas reais no Bitrix. Mantida com esta assinatura porque
    preview_novos_leads.py importa esta função diretamente deste módulo."""
    return _find_matching_lead_ids(
        phone_key,
        email,
        full_name,
        lookup_by_phone=find_lead_ids_by_phone,
        lookup_by_email=find_lead_ids_by_email,
        lookup_by_name=find_lead_ids_by_name,
    )


def find_matching_contact_ids(phone_key: str, email: str) -> tuple[list[int], str | None]:
    """Fina casca sobre domain.matching para Contatos (clientes) — telefone
    e e-mail só, sem fallback por nome (ver domain/matching.py)."""
    return _find_matching_contact_ids(
        phone_key,
        email,
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


def create_lead_from_participant(participant: dict, phone_raw: str, email: str, event_name: str, event_date: str, sympla_event_id: str, filtrar_evento_id: str, stats: dict, field_config: dict, cupom: str, valores_disponiveis: dict, extra_mapeamentos: list[dict], contact_id: int | None = None, item_id: int | None = None) -> int:
    """Cria um Lead novo. contact_id/item_id são usados no branch "cliente"
    (Contato já existente sem Lead aberto no funil): mesma lógica de
    cupom→assessor/origem de sempre também se aplica aqui — decisão
    confirmada com o usuário, um cliente que se inscreve com cupom de um
    assessor ainda deve gerar essa atribuição. Retorna o ID do Lead criado."""
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
    fields.update(resolve_extra_fields(valores_disponiveis, extra_mapeamentos, lead=None))

    new_id = bitrix_call("crm.lead.add", {"fields": fields})
    stats["leads_criados"] += 1
    responsavel_info = f", responsável={assessor_email}" if assessor_email else ""
    log.info("Novo lead %s criado pro participante %s (%s) — origem=%s%s.", new_id, participant.get("id"), name, origem_valor, responsavel_info)
    return int(new_id)


def _process_cliente_participant(contact_ids: list[int], participant: dict, phone_raw: str, email: str, event_name: str, event_date: str, event_id: str, filtrar_evento_id: str, stats: dict, field_config: dict, cupom: str, valores_disponiveis: dict, extra_mapeamentos: list[dict], item_id: int | None, force: bool) -> None:
    """Branch "cliente": o inscrito bateu com um Contato já existente.
    Vincula o Contato ao item do evento; se o Contato não tem nenhum Lead
    aberto no funil, cria um Lead novo (mesma lógica de cupom→assessor de
    sempre); se já tem, só garante que esse(s) Lead(s) também fiquem
    vinculados ao evento — não mexe em estágio/responsável de um Lead que
    já existia.

    Se bater com MAIS de um Contato (dado duplicado pré-existente no
    Bitrix — mesmo e-mail/telefone em dois registros — não causado pela
    automação), processa só o de ID mais baixo (domain.matching::
    choose_primary_contact_id) e REGISTRA o duplicado em
    execucoes_log_itens pra revisão/mesclagem manual, em vez de criar um
    Lead por Contato duplicado. Mesclar Contatos de verdade é uma tarefa
    separada — mexe em dado real de cliente (histórico de negociação,
    atividades), risco maior do que qualquer coisa que a automação já faz."""
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

    for contact_id in contact_ids:
        contact = bitrix_call("crm.contact.get", {"id": contact_id})
        if item_id and (force or not _already_linked_to_item(contact, item_id)):
            bitrix_call("crm.contact.update", {"id": contact_id, "fields": {FIELD_PARENT_ID_EVENTO_SPA: item_id}})
            log.info("Contato %s vinculado ao evento %s (item %s).", contact_id, event_name, item_id)

        open_lead_ids = _find_open_lead_ids_for_contact(contact_id)
        if contact_needs_new_lead(open_lead_ids):
            create_lead_from_participant(
                participant, phone_raw, email, event_name, event_date, event_id, filtrar_evento_id,
                stats, field_config, cupom, valores_disponiveis, extra_mapeamentos,
                contact_id=contact_id, item_id=item_id,
            )
        else:
            for lead_id in open_lead_ids:
                if not item_id:
                    continue
                lead = get_lead(lead_id)
                if force or not _already_linked_to_item(lead, item_id):
                    bitrix_call("crm.lead.update", {"id": lead_id, "fields": {FIELD_PARENT_ID_EVENTO_SPA: item_id}})
                    stats["leads_atualizados"] += 1
                    log.info("Lead %s (cliente já com Lead aberto) vinculado ao evento %s (item %s).", lead_id, event_name, item_id)


def process_participant(participant: dict, event_name: str, event_date: str, event_id: str, filtrar_evento_id: str, get_cupom_map, stats: dict, field_config: dict, extra_mapeamentos: list[dict], item_id: int | None = None, force: bool = False) -> bool:
    """Retorna True se o inscrito foi tratado com sucesso (atualizado, criado,
    ou legitimamente pulado — funil antigo/sem telefone), False se algo deu
    errado e precisa ser tentado de novo na próxima execução. Só entra na
    marca de "já processado" quem retorna True — assim uma falha transitória
    (permissão, campo faltando, rede) nunca faz a gente perder o inscrito
    pra sempre.

    force=True ("Forçar atualização de campos" no painel) reenvia os campos
    de evento mesmo que já estejam iguais — não afeta a lógica de STATUS_ID
    nem a defesa de funil antigo, só os campos de data/nome/id do evento.

    item_id (id do item na SPA "Eventos Sympla") é resolvido uma vez por
    evento em process_event() — pode ser None se a SPA estiver indisponível
    (fail-aberto), nesse caso simplesmente não vincula nada à SPA nesta
    rodada, sem afetar a sincronização de Lead/Contato de verdade.

    Roda a cascata de Contato (cliente) ANTES da cascata de Lead
    (prospect) — ver domain/matching.py::find_matching_contact_ids."""
    phone_raw = extract_phone(participant)
    phone_key = format_phone_br(phone_raw)
    email = participant.get("email") or ""
    full_name = participant_full_name(participant)
    cupom = extract_discount_code(participant, get_cupom_map)
    valores_disponiveis = {
        "cupom_desconto": cupom,
        "telefone": phone_key,
        "nome_completo": full_name,
        "email": email,
    }

    try:
        contact_ids, _contact_match_method = find_matching_contact_ids(phone_key, email)
    except Exception as exc:
        log.error("Falha ao buscar contato (cliente) pro inscrito %s: %s", participant.get("id"), exc)
        stats["erros"] += 1
        return False

    if contact_ids:
        try:
            _process_cliente_participant(contact_ids, participant, phone_raw, email, event_name, event_date, event_id, filtrar_evento_id, stats, field_config, cupom, valores_disponiveis, extra_mapeamentos, item_id, force)
            return True
        except Exception as exc:
            log.error("Falha ao processar cliente (contato) pro inscrito %s: %s", participant.get("id"), exc)
            stats["erros"] += 1
            return False

    try:
        lead_ids, match_method = find_matching_lead_ids(phone_key, email, full_name)
    except Exception as exc:
        log.error("Falha ao buscar lead pro inscrito %s: %s", participant.get("id"), exc)
        stats["erros"] += 1
        return False

    try:
        if lead_ids:
            for lead_id in lead_ids:
                lead = get_lead(lead_id)
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
                    # mude de regra no futuro.
                    fields.pop("STATUS_ID", None)
                fields.update(resolve_extra_fields(valores_disponiveis, extra_mapeamentos, lead=lead, force=force))
                if item_id and (force or not _already_linked_to_item(lead, item_id)):
                    fields[FIELD_PARENT_ID_EVENTO_SPA] = item_id
                if fields:
                    bitrix_call("crm.lead.update", {"id": lead_id, "fields": fields})
                    stats["leads_atualizados"] += 1
                    tag = " (funil antigo, só campos de evento)" if is_old_funnel else ""
                    log.info("Lead %s atualizado (match por %s)%s: %s", lead_id, match_method, tag, fields)
                else:
                    log.info("Lead %s já estava em dia, nada pra atualizar.", lead_id)
        elif phone_key:
            create_lead_from_participant(participant, phone_raw, email, event_name, event_date, event_id, filtrar_evento_id, stats, field_config, cupom, valores_disponiveis, extra_mapeamentos, item_id=item_id)
        else:
            log.warning("Inscrito sem telefone e sem nome/e-mail batendo com Lead existente, pulando: %s", participant.get("id"))
        return True
    except Exception as exc:
        log.error("Falha ao processar inscrito %s: %s", participant.get("id"), exc)
        stats["erros"] += 1
        return False


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
    sincronização de verdade."""
    event_id = event["id"]
    event_name = event.get("name", "")
    event_date = (event.get("start_date") or "")[:10]  # YYYY-MM-DD
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

    field_config = _resolve_field_config()
    extra_mapeamentos = campo_mapeamento_service.load_mapeamentos()

    filtrar_evento_id = ""
    if field_config["field_filtrar_evento"]:
        label = format_event_label(event_name, event_date)
        try:
            filtrar_evento_id = ensure_enum_value(field_config["field_filtrar_evento"], label)
        except Exception as exc:
            log.error("Falha ao garantir item '%s' na lista do campo %s: %s", label, field_config["field_filtrar_evento"], exc)

    get_cupom_map = build_cupom_map_loader(event_id)
    newly_done = {
        str(participant.get("id"))
        for participant in participants_to_process
        if process_participant(participant, event_name, event_date, event_id, filtrar_evento_id, get_cupom_map, stats, field_config, extra_mapeamentos, item_id=item_id, force=force)
    }

    if not newly_done:
        _log_item("ok")
        return False

    try:
        processed_repo.mark_processed_batch(event_id, newly_done)
    except Exception as exc:
        # Os Leads já foram atualizados/criados no Bitrix com sucesso — só
        # a marca de idempotência falhou. Não perde o inscrito: na pior das
        # hipóteses ele é reprocessado (idempotente) na próxima execução.
        log.warning("Falha ao marcar %d participante(s) como processados em %s: %s", len(newly_done), event_id, exc)

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
    de sync_all_upcoming_events."""
    iniciado_em = datetime.now(timezone.utc)
    events = list_upcoming_events()
    event = next((e for e in events if e["id"] == event_id), None)
    if event is None:
        raise ValueError(f"Evento {event_id} não encontrado entre os eventos próximos da Sympla.")

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
