"""
Ponto de entrada do painel administrativo (Dashboard/Eventos/Mapeamento/
Cupons/Logs/Verificação de Duplicados).

Uso local:
    flask --app interface_app run --port 5002
"""

import logging

from interface import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
