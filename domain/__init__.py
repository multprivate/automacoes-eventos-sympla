"""
Regras de negócio puras da Automação A: decisões, não side effects. Nada
aqui importa `requests`, `common.bitrix_client` ou `common.sympla_client` —
o objetivo é poder testar "o que a automação decide fazer" sem precisar de
nenhuma credencial nem rede.

Quem orquestra (busca dados reais, chama o Bitrix) é automacao_a_inscricoes.py.
"""
