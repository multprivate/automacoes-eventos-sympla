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


FUNIL_ETAPAS = [
    ("inscrito", "Inscritos pro evento"),
    ("pos_evento", "Pós Evento"),
    ("reuniao", "Reunião marcada"),
    ("convertido", "Negócio gerado"),
]


def montar_funil_barras(funil: dict | None) -> list[dict] | None:
    """Formata o resumo_funil (domain/funil_conversao.py) pras 4 barras da
    tela: rótulo + valor + % de largura relativa ao primeiro degrau
    (Inscritos pro evento, sempre o maior — funil cumulativo, ver
    domain/funil_conversao.py). None quando não há dado de funil (evento
    nunca vinculado à SPA "Eventos Sympla", ou falha ao consultar o
    Bitrix) — a tela mostra um aviso no lugar das barras."""
    if funil is None:
        return None
    base = funil["inscrito"] or 1
    return [
        {"chave": chave, "rotulo": rotulo, "valor": funil[chave], "pct": round(100 * funil[chave] / base)}
        for chave, rotulo in FUNIL_ETAPAS
    ]


def filter_linhas(linhas: list[dict], q: str = "", status: str = "", etapa: str = "") -> list[dict]:
    """Filtro server-side pra aba Inscritos — `q` casa substring (sem
    diferenciar maiúsculas) em nome OU e-mail; `status` casa exato contra
    "cliente"/"prospect"/"nao_verificado" (calculado em build_inscritos_view,
    a partir de participantes_processados); `etapa` casa exato contra o
    bucket do funil do Lead vinculado (linha["etapa_bucket"], preenchido em
    interface/routes_eventos.py::_montar_dados_evento a partir do estágio
    ATUAL no Bitrix — "inscrito"/"pos_evento"/"reuniao"/"convertido"/
    "perdido"/"fora_do_funil"). status e etapa são independentes: um
    inscrito pode ser "cliente" (bateu com um Contato) e o Lead dele estar
    em qualquer etapa do funil.

    Todos em branco = não filtra nada. Aplicado só na LISTAGEM — o
    resumo/funil da tela continuam calculados sobre o evento inteiro
    (interface/routes_eventos.py), pra filtrar não dar a impressão de que
    a taxa de conversão mudou."""
    resultado = linhas
    if q:
        termo = q.strip().lower()
        resultado = [l for l in resultado if termo in l["nome"].lower() or termo in l["email"].lower()]
    if status:
        resultado = [l for l in resultado if l["status"] == status]
    if etapa:
        resultado = [l for l in resultado if l["etapa_bucket"] == etapa]
    return resultado


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
