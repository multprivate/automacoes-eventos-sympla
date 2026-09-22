"""
Mantém as opções do campo de Lead "Cliente convidado para:" com todos os
eventos da Sympla, da data mais recente pra mais antiga. Wrapper de CLI
fino sobre services/campo_convidado_service.py — pensado pra rodar via
GitHub Actions, uma vez por dia (tarefa de baixa urgência, não reage a
inscrição nova de ninguém).

Uso:
    python sincronizar_lista_convidados.py
"""

import logging

from services.campo_convidado_service import sincronizar_opcoes_evento

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sincronizar_lista_convidados")


def main() -> None:
    resultado = sincronizar_opcoes_evento()
    log.info("Execução concluída: %s", resultado)


if __name__ == "__main__":
    main()
