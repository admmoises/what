"""
Funções auxiliares para o bot de trading.
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN


def timestamp_iso() -> str:
    """Retorna timestamp atual em formato ISO 8601 UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def formatar_preco(preco: float | str | Decimal, casas_decimais: int = 2) -> str:
    """
    Formata preço com número específico de casas decimais.

    Args:
        preco: Valor do preço.
        casas_decimais: Número de casas decimais.

    Returns:
        Preço formatado como string.
    """
    d = Decimal(str(preco))
    formato = Decimal(10) ** -casas_decimais
    return str(d.quantize(formato, rounding=ROUND_DOWN))


def formatar_quantidade(quantidade: float | str | Decimal, casas_decimais: int = 6) -> str:
    """
    Formata quantidade com número específico de casas decimais.

    Args:
        quantidade: Valor da quantidade.
        casas_decimais: Número de casas decimais.

    Returns:
        Quantidade formatada como string.
    """
    d = Decimal(str(quantidade))
    formato = Decimal(10) ** -casas_decimais
    return str(d.quantize(formato, rounding=ROUND_DOWN))


def calcular_preco_medio(precos: list[float], pesos: list[float] | None = None) -> float:
    """
    Calcula preço médio ponderado.

    Args:
        precos: Lista de preços.
        pesos: Lista de pesos (opcional, usa peso igual se None).

    Returns:
        Preço médio ponderado.
    """
    if not precos:
        return 0.0

    if pesos is None:
        return sum(precos) / len(precos)

    if len(precos) != len(pesos):
        raise ValueError("Listas de preços e pesos devem ter o mesmo tamanho")

    soma_ponderada = sum(p * w for p, w in zip(precos, pesos))
    soma_pesos = sum(pesos)

    if soma_pesos == 0:
        return 0.0

    return soma_ponderada / soma_pesos


def calcular_variacao_percentual(preco_antigo: float, preco_novo: float) -> float:
    """Calcula variação percentual entre dois preços."""
    if preco_antigo == 0:
        return 0.0
    return ((preco_novo - preco_antigo) / preco_antigo) * 100
