"""
Filtros Jinja do painel. Todo timestamp é gravado em UTC (prática certa
pro banco) — esse filtro só converte pra exibição, nunca mexe no que é
armazenado.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BRT = ZoneInfo("America/Fortaleza")


def to_brt(iso_utc: str | None) -> str:
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc)
    except ValueError:
        return iso_utc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BRT).strftime("%d/%m/%Y %H:%M")
