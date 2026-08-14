"""
Varredura periódica que acha Leads duplicados por telefone além do que
`crm.duplicate.findbycomm` (usado em tempo real pela Automação A) já
cobre — existe pra pegar os dois casos que a cascata em tempo real não
alcança: Leads criados manualmente na tela do Bitrix (nunca passam pelo
nosso código) e números com formatação/dígito divergente entre si (ex:
celular de 8 x 9 dígitos, com/sem +55).

Nunca mescla sozinho: só grava candidato pendente em
duplicados_candidatos, pra um humano decidir na aba "Verificação de
Duplicados" do painel — telefone compartilhado por pessoas DIFERENTES
(família, casal) já mordeu a gente antes (Kátia+Juvenal, Vitor+Luana,
família Quesado), então mesclagem automática por telefone sozinho é
arriscada demais.
"""

import logging

from common import LEAD_CLOSED_STAGES, bitrix_call, bitrix_list_all, get_lead, normalize_phone_suffix
from common.constants import FIELD_PARENT_ID_EVENTO_SPA
from domain.matching import choose_primary_lead_id
from repositories import duplicados_repo

log = logging.getLogger("services.duplicidade_service")

LEAD_OWNER_TYPE_ID = 1  # CRM_OWNERTYPE_LEAD, usado em crm.activity.list


def _first_phone_value(lead: dict) -> str:
    phones = lead.get("PHONE") or []
    return phones[0].get("VALUE", "") if phones else ""


def _new_stats() -> dict:
    return {"leads_verificados": 0, "grupos_com_duplicata": 0, "candidatos_novos": 0, "erros": 0}


def detectar_duplicados_por_telefone() -> dict:
    stats = _new_stats()

    leads = bitrix_list_all(
        "crm.lead.list",
        {"filter": {"!STATUS_ID": list(LEAD_CLOSED_STAGES)}, "select": ["ID", "NAME", "STATUS_ID", "PHONE"]},
    )
    stats["leads_verificados"] = len(leads)

    grupos: dict[str, list[dict]] = {}
    for lead in leads:
        chave = normalize_phone_suffix(_first_phone_value(lead))
        if not chave:
            continue
        grupos.setdefault(chave, []).append(lead)

    for chave, membros in grupos.items():
        if len(membros) < 2:
            continue
        stats["grupos_com_duplicata"] += 1
        membros_ordenados = sorted(membros, key=lambda lead: int(lead["ID"]))
        ancora = membros_ordenados[0]
        ancora_id = int(ancora["ID"])
        for outro in membros_ordenados[1:]:
            outro_id = int(outro["ID"])
            try:
                if duplicados_repo.existe_par(ancora_id, outro_id):
                    continue
                duplicados_repo.insert_candidato(
                    lead_id_a=ancora_id,
                    lead_id_b=outro_id,
                    nome_a=ancora.get("NAME", ""),
                    nome_b=outro.get("NAME", ""),
                    telefone_a=_first_phone_value(ancora),
                    telefone_b=_first_phone_value(outro),
                )
                stats["candidatos_novos"] += 1
            except Exception as exc:
                stats["erros"] += 1
                log.error("Falha ao registrar candidato a duplicado (%s, %s): %s", ancora_id, outro_id, exc)

    return stats


def _contar_activities(lead_id: int) -> list[dict]:
    return bitrix_list_all(
        "crm.activity.list",
        {
            "filter": {"OWNER_TYPE_ID": LEAD_OWNER_TYPE_ID, "OWNER_ID": lead_id},
            "select": ["ID", "SUBJECT", "DESCRIPTION", "CREATED"],
        },
    )


def _comentario_activities_preservadas(secundario_id: int, nome_secundario: str, activities: list[dict]) -> str:
    linhas = [f"Lead duplicado #{secundario_id} ({nome_secundario}) mesclado aqui e removido."]
    if activities:
        linhas.append(f"Ele tinha {len(activities)} atividade(s) registrada(s):")
        for act in activities:
            assunto = act.get("SUBJECT") or "(sem assunto)"
            linhas.append(f"- [{act.get('CREATED', '?')}] {assunto}")
    return "\n".join(linhas)


def executar_merge(candidato_id: str) -> dict:
    candidato = duplicados_repo.get_by_id(candidato_id)
    if not candidato:
        raise ValueError(f"Candidato {candidato_id} não encontrado.")
    if candidato["status"] != "pendente":
        raise ValueError(f"Candidato {candidato_id} já foi resolvido (status='{candidato['status']}').")

    lead_a_id = int(candidato["lead_id_a"])
    lead_b_id = int(candidato["lead_id_b"])
    lead_a = get_lead(lead_a_id)
    lead_b = get_lead(lead_b_id)

    activities_a = _contar_activities(lead_a_id)
    activities_b = _contar_activities(lead_b_id)

    primary_id, secondary_id = choose_primary_lead_id(
        lead_a_id,
        lead_b_id,
        tem_vinculo_spa_a=bool(lead_a.get(FIELD_PARENT_ID_EVENTO_SPA)),
        tem_vinculo_spa_b=bool(lead_b.get(FIELD_PARENT_ID_EVENTO_SPA)),
        tem_email_a=bool(lead_a.get("EMAIL")),
        tem_email_b=bool(lead_b.get("EMAIL")),
        activities_a=len(activities_a),
        activities_b=len(activities_b),
    )
    primary = lead_a if primary_id == lead_a_id else lead_b
    secondary = lead_b if primary_id == lead_a_id else lead_a
    secondary_activities = activities_b if primary_id == lead_a_id else activities_a

    if secondary.get("CONTACT_ID") and not primary.get("CONTACT_ID"):
        bitrix_call("crm.lead.update", {"id": primary_id, "fields": {"CONTACT_ID": secondary["CONTACT_ID"]}})

    comentario = _comentario_activities_preservadas(secondary_id, secondary.get("NAME", ""), secondary_activities)
    bitrix_call("crm.timeline.comment.add", {"fields": {"ENTITY_ID": primary_id, "ENTITY_TYPE": "lead", "COMMENT": comentario}})

    bitrix_call("crm.lead.delete", {"id": secondary_id})
    duplicados_repo.set_status(candidato_id, "mesclado")

    log.info("Candidato %s mesclado: Lead %s (principal) absorveu Lead %s (removido).", candidato_id, primary_id, secondary_id)
    return {"primary_id": primary_id, "secondary_id": secondary_id}


def ignorar(candidato_id: str) -> None:
    candidato = duplicados_repo.get_by_id(candidato_id)
    if not candidato:
        raise ValueError(f"Candidato {candidato_id} não encontrado.")
    duplicados_repo.set_status(candidato_id, "ignorado")
