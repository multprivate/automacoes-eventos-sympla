"""
Monta a view da aba "Inscritos" de um evento (interface/routes_eventos.py::
inscritos) — junta a lista viva da Sympla (identidade: nome/e-mail/
telefone/CPF/check-in, barata, nunca persistida) com o resultado do match
gravado em participantes_processados (cliente ou não, por qual sinal, qual
card no Bitrix, quando foi encontrado — migração 0006).

Puro, sem I/O, mesmo espírito de eventos_helper.py — quem busca os dados
(Sympla + Supabase) é a rota; este módulo só decide como exibi-los.
"""

from common import extract_cpf, extract_phone, format_phone_br, participant_full_name


def build_inscritos_view(participants: list[dict], resultados: dict[str, dict]) -> list[dict]:
    """Inscrito sem linha correspondente em `resultados` = nunca
    sincronizado, OU sincronizado antes da migração 0006 (que não pôde
    fazer backfill: o resultado do match nunca foi capturado
    historicamente). Os dois casos viram status "nao_verificado" — a
    diferença entre eles é visível pelo processado_em, que existe até em
    linha legada (só as colunas novas é que ficam None)."""
    linhas = []
    for participant in participants:
        participant_id = str(participant.get("id"))
        resultado = resultados.get(participant_id)

        if resultado is None or resultado.get("is_cliente") is None:
            status = "nao_verificado"
        elif resultado["is_cliente"]:
            status = "cliente"
        else:
            status = "prospect"

        contact_ids_duplicados = (resultado or {}).get("contact_ids_duplicados")

        linhas.append({
            "participant_id": participant_id,
            "nome": participant_full_name(participant),
            "email": participant.get("email") or "",
            "telefone": format_phone_br(extract_phone(participant)),
            "cpf": extract_cpf(participant),
            "checkin": bool((participant.get("checkin") or {}).get("check_in_date")),
            "status": status,
            "match_method": (resultado or {}).get("match_method"),
            "processado_em": (resultado or {}).get("processado_em"),
            "verificado_em": (resultado or {}).get("verificado_em"),
            "contact_id": (resultado or {}).get("bitrix_contact_id"),
            "lead_id": (resultado or {}).get("bitrix_lead_id"),
            "contact_ids_duplicados": contact_ids_duplicados,
            "tem_duplicado": bool(contact_ids_duplicados),
        })
    return linhas


def resumo_conversao(linhas: list[dict]) -> dict:
    """{total, clientes, prospects, nao_verificados, taxa_pct}. taxa_pct
    usa como denominador só os VERIFICADOS (clientes + prospects), não o
    total de inscritos: contar quem ainda não foi verificado como "não
    era cliente" subestimaria a taxa, e ela mudaria sozinha conforme o
    evento vai sincronizando aos poucos. taxa_pct é 0 quando ninguém
    ainda foi verificado (sem divisão por zero)."""
    total = len(linhas)
    clientes = sum(1 for l in linhas if l["status"] == "cliente")
    prospects = sum(1 for l in linhas if l["status"] == "prospect")
    nao_verificados = total - clientes - prospects
    verificados = clientes + prospects
    taxa_pct = round(100 * clientes / verificados) if verificados else 0
    return {
        "total": total,
        "clientes": clientes,
        "prospects": prospects,
        "nao_verificados": nao_verificados,
        "taxa_pct": taxa_pct,
    }
