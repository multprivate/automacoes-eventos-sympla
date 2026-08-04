"""
Camada de orquestração: liga as decisões puras de domain/ aos dados reais
(Bitrix, Sympla, Supabase via repositories/). Onde vive retry/fallback
entre fontes de dado — não é lugar de regra de negócio nova.
"""
