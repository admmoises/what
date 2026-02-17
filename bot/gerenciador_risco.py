"""
Gerenciador de Risco.

Implementa controles de risco para proteger o capital,
incluindo limites de posição, stop-loss e controle de drawdown.
"""

import time
from dataclasses import dataclass, field
from typing import Any

from bot.utils.logger import configurar_logger

logger = configurar_logger("risco")


@dataclass
class ConfiguracaoRisco:
    """Parâmetros de gerenciamento de risco."""
    # Limites de posição
    tamanho_maximo_ordem: float = 0.0
    exposicao_maxima: float = 0.0  # Valor total máximo em posições abertas

    # Stop-loss
    stop_loss_percentual: float = 2.0  # % de perda máxima por trade
    stop_loss_diario: float = 5.0  # % de perda máxima diária

    # Controle de ordens
    max_ordens_abertas: int = 10
    max_ordens_por_minuto: int = 30

    # Drawdown
    drawdown_maximo: float = 10.0  # % de drawdown máximo permitido

    # Kill switch - para tudo se ativado
    kill_switch_perda: float = 15.0  # % de perda que ativa kill switch


@dataclass
class EstadoRisco:
    """Estado atual do gerenciamento de risco."""
    capital_inicial: float = 0.0
    capital_atual: float = 0.0
    pico_capital: float = 0.0
    pnl_diario: float = 0.0
    pnl_total: float = 0.0
    ordens_no_minuto: list[float] = field(default_factory=list)
    kill_switch_ativado: bool = False
    motivo_kill_switch: str = ""
    timestamp_inicio_dia: float = field(default_factory=time.time)

    @property
    def drawdown_atual(self) -> float:
        """Calcula drawdown atual em percentual."""
        if self.pico_capital == 0:
            return 0.0
        return ((self.pico_capital - self.capital_atual) / self.pico_capital) * 100

    @property
    def retorno_diario(self) -> float:
        """Retorno percentual do dia."""
        if self.capital_inicial == 0:
            return 0.0
        return (self.pnl_diario / self.capital_inicial) * 100


class GerenciadorRisco:
    """
    Gerencia o risco operacional do bot de trading.

    Verifica limites antes de cada operação e pode ativar
    o kill switch para parar toda atividade em caso de perdas excessivas.
    """

    def __init__(self, config: ConfiguracaoRisco):
        self._config = config
        self._estado = EstadoRisco()

    @property
    def estado(self) -> EstadoRisco:
        return self._estado

    @property
    def kill_switch_ativo(self) -> bool:
        return self._estado.kill_switch_ativado

    def inicializar(self, capital_inicial: float):
        """
        Inicializa o gerenciador com o capital disponível.

        Args:
            capital_inicial: Capital total disponível.
        """
        self._estado.capital_inicial = capital_inicial
        self._estado.capital_atual = capital_inicial
        self._estado.pico_capital = capital_inicial
        self._estado.pnl_diario = 0.0
        self._estado.timestamp_inicio_dia = time.time()
        logger.info(f"Gerenciador de risco inicializado com capital: {capital_inicial}")

    def atualizar_capital(self, capital_atual: float):
        """
        Atualiza o capital atual e recalcula métricas.

        Args:
            capital_atual: Capital total atual.
        """
        self._estado.capital_atual = capital_atual
        self._estado.pnl_total = capital_atual - self._estado.capital_inicial

        # Atualizar pico
        if capital_atual > self._estado.pico_capital:
            self._estado.pico_capital = capital_atual

        # Verificar kill switch
        self._verificar_kill_switch()

    def registrar_pnl(self, pnl: float):
        """
        Registra PnL de uma operação.

        Args:
            pnl: Lucro ou prejuízo da operação.
        """
        self._estado.pnl_diario += pnl
        self._estado.pnl_total += pnl
        self._estado.capital_atual += pnl

        if self._estado.capital_atual > self._estado.pico_capital:
            self._estado.pico_capital = self._estado.capital_atual

        logger.info(
            f"PnL registrado: {pnl:+.4f} | "
            f"Diário: {self._estado.pnl_diario:+.4f} | "
            f"Total: {self._estado.pnl_total:+.4f}"
        )

        self._verificar_kill_switch()

    def pode_criar_ordem(
        self,
        tamanho: float,
        num_ordens_ativas: int,
    ) -> tuple[bool, str]:
        """
        Verifica se uma nova ordem pode ser criada.

        Args:
            tamanho: Tamanho da ordem em valor.
            num_ordens_ativas: Número atual de ordens abertas.

        Returns:
            Tupla (permitido, motivo).
        """
        # Kill switch
        if self._estado.kill_switch_ativado:
            return False, f"Kill switch ativado: {self._estado.motivo_kill_switch}"

        # Limite de tamanho
        if self._config.tamanho_maximo_ordem > 0 and tamanho > self._config.tamanho_maximo_ordem:
            return False, (
                f"Tamanho da ordem ({tamanho}) excede limite "
                f"({self._config.tamanho_maximo_ordem})"
            )

        # Limite de ordens abertas
        if num_ordens_ativas >= self._config.max_ordens_abertas:
            return False, (
                f"Limite de ordens abertas atingido ({self._config.max_ordens_abertas})"
            )

        # Rate limit
        agora = time.time()
        self._estado.ordens_no_minuto = [
            t for t in self._estado.ordens_no_minuto if agora - t < 60
        ]
        if len(self._estado.ordens_no_minuto) >= self._config.max_ordens_por_minuto:
            return False, (
                f"Limite de ordens por minuto atingido ({self._config.max_ordens_por_minuto})"
            )

        # Stop-loss diário
        if self._estado.capital_inicial > 0:
            perda_diaria_pct = abs(min(0, self._estado.retorno_diario))
            if perda_diaria_pct >= self._config.stop_loss_diario:
                return False, (
                    f"Stop-loss diário atingido ({perda_diaria_pct:.2f}% >= "
                    f"{self._config.stop_loss_diario}%)"
                )

        # Drawdown máximo
        if self._estado.drawdown_atual >= self._config.drawdown_maximo:
            return False, (
                f"Drawdown máximo atingido ({self._estado.drawdown_atual:.2f}% >= "
                f"{self._config.drawdown_maximo}%)"
            )

        # Registrar tentativa
        self._estado.ordens_no_minuto.append(agora)

        return True, "OK"

    def verificar_stop_loss_ordem(self, preco_entrada: float, preco_atual: float, lado: str) -> bool:
        """
        Verifica se o stop-loss de uma ordem individual foi atingido.

        Args:
            preco_entrada: Preço de entrada.
            preco_atual: Preço atual.
            lado: 'buy' ou 'sell'.

        Returns:
            True se stop-loss foi atingido.
        """
        if lado == "buy":
            variacao = ((preco_atual - preco_entrada) / preco_entrada) * 100
            if variacao <= -self._config.stop_loss_percentual:
                logger.warning(
                    f"Stop-loss atingido: entrada={preco_entrada} "
                    f"atual={preco_atual} variação={variacao:.2f}%"
                )
                return True
        elif lado == "sell":
            variacao = ((preco_entrada - preco_atual) / preco_entrada) * 100
            if variacao <= -self._config.stop_loss_percentual:
                logger.warning(
                    f"Stop-loss atingido (short): entrada={preco_entrada} "
                    f"atual={preco_atual} variação={variacao:.2f}%"
                )
                return True

        return False

    def _verificar_kill_switch(self):
        """Verifica se o kill switch deve ser ativado."""
        if self._estado.kill_switch_ativado:
            return

        if self._estado.capital_inicial == 0:
            return

        perda_total_pct = ((self._estado.capital_inicial - self._estado.capital_atual)
                          / self._estado.capital_inicial) * 100

        if perda_total_pct >= self._config.kill_switch_perda:
            self._estado.kill_switch_ativado = True
            self._estado.motivo_kill_switch = (
                f"Perda total de {perda_total_pct:.2f}% excede limite de "
                f"{self._config.kill_switch_perda}%"
            )
            logger.critical(f"KILL SWITCH ATIVADO: {self._estado.motivo_kill_switch}")

    def resetar_pnl_diario(self):
        """Reseta o PnL diário (chamado no início de cada dia)."""
        logger.info(f"PnL diário resetado. Resultado anterior: {self._estado.pnl_diario:+.4f}")
        self._estado.pnl_diario = 0.0
        self._estado.timestamp_inicio_dia = time.time()
        self._estado.ordens_no_minuto.clear()

    def desativar_kill_switch(self):
        """Desativa kill switch manualmente (requer confirmação do operador)."""
        self._estado.kill_switch_ativado = False
        self._estado.motivo_kill_switch = ""
        logger.warning("Kill switch desativado manualmente")

    def obter_relatorio(self) -> dict:
        """Retorna relatório completo do estado de risco."""
        return {
            "capital_inicial": self._estado.capital_inicial,
            "capital_atual": self._estado.capital_atual,
            "pico_capital": self._estado.pico_capital,
            "pnl_diario": self._estado.pnl_diario,
            "pnl_total": self._estado.pnl_total,
            "retorno_diario_pct": self._estado.retorno_diario,
            "drawdown_atual_pct": self._estado.drawdown_atual,
            "kill_switch": self._estado.kill_switch_ativado,
            "ordens_ultimo_minuto": len(self._estado.ordens_no_minuto),
        }
