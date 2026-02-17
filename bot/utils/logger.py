"""
Configuração de logging para o bot de trading.
"""

import logging
import sys
from pathlib import Path
from datetime import datetime


def configurar_logger(
    nome: str = "okx_bot",
    nivel: str = "INFO",
    arquivo_log: str | None = None,
) -> logging.Logger:
    """
    Configura e retorna um logger.

    Args:
        nome: Nome do logger.
        nivel: Nível de logging (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        arquivo_log: Caminho para arquivo de log. Se None, cria automaticamente.

    Returns:
        Logger configurado.
    """
    logger = logging.getLogger(nome)
    logger.setLevel(getattr(logging, nivel.upper(), logging.INFO))

    if logger.handlers:
        return logger

    formato = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Handler para console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formato)
    logger.addHandler(console_handler)

    # Handler para arquivo
    if arquivo_log is None:
        pasta_logs = Path("logs")
        pasta_logs.mkdir(exist_ok=True)
        data = datetime.now().strftime("%Y%m%d")
        arquivo_log = str(pasta_logs / f"bot_{data}.log")

    arquivo_handler = logging.FileHandler(arquivo_log, encoding="utf-8")
    arquivo_handler.setFormatter(formato)
    logger.addHandler(arquivo_handler)

    return logger
