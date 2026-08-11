"""
Varredura de duplicados: wrapper de CLI fino sobre services/
duplicidade_service.py — chama detectar_duplicados_por_telefone() e
loga o resultado. Toda a lógica vive no serviço; este módulo só existe
como ponto de entrada de linha de comando (pensado pra rodar via GitHub
Actions, uma vez por dia).

Uso:
    python verificar_duplicados.py
"""

import logging

from services.duplicidade_service import detectar_duplicados_por_telefone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("verificar_duplicados")


def main() -> None:
    stats = detectar_duplicados_por_telefone()
    log.info("Execução concluída: %s", stats)


if __name__ == "__main__":
    main()
