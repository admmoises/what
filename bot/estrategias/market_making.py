"""
Estratégia de Market Making.

Coloca ordens de compra e venda simultaneamente ao redor do preço
de mercado, lucrando com o spread entre bid e ask.
"""

from dataclasses import dataclass

from bot.cliente_okx import ClienteOKX, LadoOrdem
from bot.gerenciador_ordens import GerenciadorOrdens, StatusOrdem
from bot.gerenciador_risco import GerenciadorRisco
from bot.estrategias.base import EstrategiaBase, TickerAtual
from bot.utils.logger import configurar_logger

logger = configurar_logger("estrategia.market_making")


@dataclass
class ConfigMarketMaking:
    """Configuração da estratégia de Market Making."""
    # Spread
    spread_bid: float = 0.001  # 0.1% abaixo do mid
    spread_ask: float = 0.001  # 0.1% acima do mid

    # Tamanho das ordens
    tamanho_ordem: float = 0.001  # Quantidade por ordem
    num_niveis: int = 3  # Número de níveis de cada lado
    incremento_nivel: float = 0.0005  # Incremento de spread por nível

    # Controle
    rebalancear_a_cada: int = 5  # Ciclos entre rebalanceamentos
    inventario_maximo: float = 0.0  # Posição máxima acumulada (0 = sem limite)
    casas_preco: int = 2
    casas_quantidade: int = 6

    # Ajuste de inventário
    ajuste_inventario: bool = True  # Ajustar spreads baseado no inventário
    fator_ajuste: float = 0.5  # Fator de ajuste (0-1)


class EstrategiaMarketMaking(EstrategiaBase):
    """
    Estratégia de Market Making.

    Mantém ordens de compra e venda em múltiplos níveis ao redor
    do mid price, capturando o spread como lucro.

    Características:
    - Múltiplos níveis de ordens (bid e ask)
    - Ajuste dinâmico de spread baseado no inventário
    - Rebalanceamento automático de ordens
    - Integração com gerenciador de risco
    """

    def __init__(
        self,
        cliente: ClienteOKX,
        gerenciador_ordens: GerenciadorOrdens,
        gerenciador_risco: GerenciadorRisco,
        par: str,
        config: ConfigMarketMaking | None = None,
        intervalo_ciclo: float = 1.0,
    ):
        super().__init__(cliente, gerenciador_ordens, gerenciador_risco, par, intervalo_ciclo)
        self._config = config or ConfigMarketMaking()
        self._ciclo_atual = 0
        self._inventario = 0.0  # Posição líquida acumulada

    def ao_iniciar(self):
        """Configuração inicial da estratégia."""
        logger.info(
            f"Market Making iniciado para {self._par} | "
            f"Spread: {self._config.spread_bid*100:.2f}%/{self._config.spread_ask*100:.2f}% | "
            f"Níveis: {self._config.num_niveis} | "
            f"Tamanho: {self._config.tamanho_ordem}"
        )

    def ao_parar(self):
        """Limpeza ao parar."""
        self._inventario = 0.0
        logger.info("Market Making parado")

    def ao_atualizar_ordem(self, dados_ordem: dict):
        """Atualiza inventário quando ordens são preenchidas."""
        self._ordens.atualizar_ordem(dados_ordem)

        estado = dados_ordem.get("state", "")
        if estado == "filled":
            lado = dados_ordem.get("side", "")
            quantidade = float(dados_ordem.get("accFillSz", 0))

            if lado == "buy":
                self._inventario += quantidade
            elif lado == "sell":
                self._inventario -= quantidade

            logger.info(f"Inventário atualizado: {self._inventario:+.6f}")

    def _calcular_mid_price(self, ticker: TickerAtual) -> float:
        """Calcula preço médio entre bid e ask."""
        if ticker.melhor_bid > 0 and ticker.melhor_ask > 0:
            return (ticker.melhor_bid + ticker.melhor_ask) / 2
        return ticker.ultimo_preco

    def _ajustar_spread_por_inventario(self, spread_bid: float, spread_ask: float) -> tuple[float, float]:
        """
        Ajusta spreads baseado no inventário acumulado.

        Se temos inventário positivo (comprado demais), aumenta spread de compra
        e diminui spread de venda para incentivar vendas.
        """
        if not self._config.ajuste_inventario or self._inventario == 0:
            return spread_bid, spread_ask

        fator = self._config.fator_ajuste
        ajuste = self._inventario * fator * 0.0001

        spread_bid_ajustado = spread_bid + ajuste  # Compra mais barato se inventário alto
        spread_ask_ajustado = spread_ask - ajuste  # Vende mais barato se inventário alto

        # Garantir spreads mínimos
        spread_bid_ajustado = max(spread_bid_ajustado, 0.0001)
        spread_ask_ajustado = max(spread_ask_ajustado, 0.0001)

        return spread_bid_ajustado, spread_ask_ajustado

    def _criar_ordens_niveis(self, mid_price: float):
        """Cria ordens em múltiplos níveis de preço."""
        spread_bid, spread_ask = self._ajustar_spread_por_inventario(
            self._config.spread_bid, self._config.spread_ask
        )

        for nivel in range(self._config.num_niveis):
            incremento = nivel * self._config.incremento_nivel

            # Ordem de compra
            preco_bid = mid_price * (1 - spread_bid - incremento)
            permitido, motivo = self._risco.pode_criar_ordem(
                self._config.tamanho_ordem * preco_bid,
                len(self._ordens.ordens_ativas),
            )
            if permitido:
                self._ordens.criar_ordem_limite(
                    par=self._par,
                    lado=LadoOrdem.COMPRA,
                    preco=preco_bid,
                    quantidade=self._config.tamanho_ordem,
                    casas_preco=self._config.casas_preco,
                    casas_quantidade=self._config.casas_quantidade,
                )
            else:
                logger.warning(f"Ordem de compra nível {nivel} bloqueada: {motivo}")

            # Ordem de venda
            preco_ask = mid_price * (1 + spread_ask + incremento)
            permitido, motivo = self._risco.pode_criar_ordem(
                self._config.tamanho_ordem * preco_ask,
                len(self._ordens.ordens_ativas),
            )
            if permitido:
                self._ordens.criar_ordem_limite(
                    par=self._par,
                    lado=LadoOrdem.VENDA,
                    preco=preco_ask,
                    quantidade=self._config.tamanho_ordem,
                    casas_preco=self._config.casas_preco,
                    casas_quantidade=self._config.casas_quantidade,
                )
            else:
                logger.warning(f"Ordem de venda nível {nivel} bloqueada: {motivo}")

    def executar_ciclo(self, ticker: TickerAtual):
        """
        Executa um ciclo de market making.

        A cada N ciclos, cancela ordens existentes e recria
        com preços atualizados.
        """
        if self._risco.kill_switch_ativo:
            logger.warning("Kill switch ativo - ciclo ignorado")
            return

        self._ciclo_atual += 1

        mid_price = self._calcular_mid_price(ticker)
        if mid_price <= 0:
            logger.warning("Mid price inválido, ignorando ciclo")
            return

        # Verificar inventário máximo
        if self._config.inventario_maximo > 0:
            if abs(self._inventario) >= self._config.inventario_maximo:
                logger.warning(
                    f"Inventário ({self._inventario:+.6f}) atingiu limite "
                    f"({self._config.inventario_maximo})"
                )

        # Rebalancear periodicamente
        if self._ciclo_atual % self._config.rebalancear_a_cada == 0:
            logger.info(
                f"Rebalanceando | Mid: {mid_price:.{self._config.casas_preco}f} | "
                f"Inventário: {self._inventario:+.6f} | "
                f"Ordens ativas: {len(self._ordens.ordens_ativas)}"
            )

            # Cancelar ordens existentes
            self._ordens.cancelar_todas(self._par)

            # Criar novas ordens
            self._criar_ordens_niveis(mid_price)
