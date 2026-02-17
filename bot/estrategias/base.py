"""
Classe base abstrata para estratégias de trading.

Todas as estratégias devem herdar de EstrategiaBase e implementar
os métodos abstratos.
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from bot.cliente_okx import ClienteOKX
from bot.gerenciador_ordens import GerenciadorOrdens
from bot.gerenciador_risco import GerenciadorRisco
from bot.utils.logger import configurar_logger

logger = configurar_logger("estrategia.base")


@dataclass
class TickerAtual:
    """Dados de ticker em tempo real."""
    par: str = ""
    ultimo_preco: float = 0.0
    melhor_bid: float = 0.0
    melhor_ask: float = 0.0
    volume_24h: float = 0.0
    variacao_24h: float = 0.0
    timestamp: float = 0.0


@dataclass
class EstadoEstrategia:
    """Estado interno da estratégia."""
    ativa: bool = False
    ciclos_executados: int = 0
    erros_consecutivos: int = 0
    max_erros_consecutivos: int = 5
    ultimo_ticker: TickerAtual = field(default_factory=TickerAtual)


class EstrategiaBase(ABC):
    """
    Classe base para todas as estratégias de trading.

    Define a interface que todas as estratégias devem implementar
    e fornece funcionalidades comuns.
    """

    def __init__(
        self,
        cliente: ClienteOKX,
        gerenciador_ordens: GerenciadorOrdens,
        gerenciador_risco: GerenciadorRisco,
        par: str,
        intervalo_ciclo: float = 1.0,
    ):
        self._cliente = cliente
        self._ordens = gerenciador_ordens
        self._risco = gerenciador_risco
        self._par = par
        self._intervalo_ciclo = intervalo_ciclo
        self._estado = EstadoEstrategia()

    @property
    def nome(self) -> str:
        """Nome da estratégia."""
        return self.__class__.__name__

    @property
    def par(self) -> str:
        return self._par

    @property
    def ativa(self) -> bool:
        return self._estado.ativa

    @abstractmethod
    def ao_iniciar(self):
        """Chamado quando a estratégia é iniciada. Configuração inicial."""
        pass

    @abstractmethod
    def ao_parar(self):
        """Chamado quando a estratégia é parada. Limpeza."""
        pass

    @abstractmethod
    def executar_ciclo(self, ticker: TickerAtual):
        """
        Executa um ciclo da estratégia.

        Este é o método principal onde a lógica de trading é implementada.
        Chamado periodicamente pelo loop principal.

        Args:
            ticker: Dados atuais do ticker.
        """
        pass

    @abstractmethod
    def ao_atualizar_ordem(self, dados_ordem: dict):
        """
        Chamado quando uma ordem é atualizada (via WebSocket).

        Args:
            dados_ordem: Dados da ordem atualizada.
        """
        pass

    def iniciar(self):
        """Inicia a estratégia."""
        logger.info(f"Iniciando estratégia '{self.nome}' para {self._par}")
        self._estado.ativa = True
        self._estado.erros_consecutivos = 0
        self.ao_iniciar()

    def parar(self):
        """Para a estratégia e cancela ordens ativas."""
        logger.info(f"Parando estratégia '{self.nome}'")
        self._estado.ativa = False

        # Cancelar todas as ordens ativas
        canceladas = self._ordens.cancelar_todas(self._par)
        logger.info(f"Ordens canceladas ao parar: {canceladas}")

        self.ao_parar()

    def atualizar_ticker(self, dados_ticker: dict):
        """
        Atualiza ticker a partir dos dados da API/WebSocket.

        Args:
            dados_ticker: Dados do ticker da OKX.
        """
        self._estado.ultimo_ticker = TickerAtual(
            par=dados_ticker.get("instId", self._par),
            ultimo_preco=float(dados_ticker.get("last", 0)),
            melhor_bid=float(dados_ticker.get("bidPx", 0)),
            melhor_ask=float(dados_ticker.get("askPx", 0)),
            volume_24h=float(dados_ticker.get("vol24h", 0)),
            variacao_24h=float(dados_ticker.get("sodUtc0", 0)) if dados_ticker.get("sodUtc0") else 0.0,
            timestamp=float(dados_ticker.get("ts", 0)) / 1000 if dados_ticker.get("ts") else 0.0,
        )

    def _ciclo_seguro(self, ticker: TickerAtual):
        """Executa ciclo com tratamento de erros."""
        try:
            self.executar_ciclo(ticker)
            self._estado.ciclos_executados += 1
            self._estado.erros_consecutivos = 0
        except Exception as e:
            self._estado.erros_consecutivos += 1
            logger.error(
                f"Erro no ciclo {self._estado.ciclos_executados} da estratégia "
                f"'{self.nome}': {e} (erro {self._estado.erros_consecutivos}/"
                f"{self._estado.max_erros_consecutivos})"
            )

            if self._estado.erros_consecutivos >= self._estado.max_erros_consecutivos:
                logger.critical(
                    f"Muitos erros consecutivos na estratégia '{self.nome}'. Parando."
                )
                self.parar()

    async def loop_principal(self):
        """
        Loop principal assíncrono da estratégia.

        Busca ticker periodicamente e executa ciclos de trading.
        """
        logger.info(f"Loop principal iniciado para '{self.nome}' (intervalo: {self._intervalo_ciclo}s)")

        while self._estado.ativa:
            try:
                # Buscar ticker atualizado
                dados_ticker = self._cliente.obter_ticker(self._par)
                if dados_ticker:
                    self.atualizar_ticker(dados_ticker)
                    self._ciclo_seguro(self._estado.ultimo_ticker)

            except Exception as e:
                logger.error(f"Erro no loop principal: {e}")

            await asyncio.sleep(self._intervalo_ciclo)

    def obter_status(self) -> dict:
        """Retorna status da estratégia."""
        resumo_ordens = self._ordens.obter_resumo()
        return {
            "nome": self.nome,
            "par": self._par,
            "ativa": self._estado.ativa,
            "ciclos": self._estado.ciclos_executados,
            "erros_consecutivos": self._estado.erros_consecutivos,
            "ultimo_preco": self._estado.ultimo_ticker.ultimo_preco,
            "ordens": resumo_ordens,
        }
