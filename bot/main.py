"""
Módulo principal do Bot de Trading OKX.

Orquestra todos os componentes: cliente API, WebSocket,
estratégias, gerenciamento de ordens e risco.
"""

import asyncio
import json
import signal
from pathlib import Path
from typing import Any

from bot.cliente_okx import ClienteOKX, ConfiguracaoOKX, ModoTrade
from bot.websocket_okx import WebSocketOKX, AssinaturaCanal
from bot.gerenciador_ordens import GerenciadorOrdens
from bot.gerenciador_risco import GerenciadorRisco, ConfiguracaoRisco
from bot.estrategias.base import EstrategiaBase
from bot.estrategias.market_making import EstrategiaMarketMaking, ConfigMarketMaking
from bot.estrategias.grid_trading import EstrategiaGridTrading, ConfigGrid
from bot.utils.logger import configurar_logger

logger = configurar_logger("bot.principal")


class BotTrading:
    """
    Bot de Trading para OKX.

    Componente principal que coordena todas as partes do sistema:
    - Conexão REST e WebSocket com a OKX
    - Gerenciamento de ordens
    - Gerenciamento de risco
    - Execução de estratégias
    """

    def __init__(self, caminho_config: str = "config/config.json"):
        self._config: dict = {}
        self._caminho_config = caminho_config

        self._cliente: ClienteOKX | None = None
        self._websocket: WebSocketOKX | None = None
        self._gerenciador_ordens: GerenciadorOrdens | None = None
        self._gerenciador_risco: GerenciadorRisco | None = None
        self._estrategia: EstrategiaBase | None = None
        self._rodando = False

    def carregar_configuracao(self) -> dict:
        """
        Carrega configuração do arquivo JSON.

        Returns:
            Dicionário de configuração.

        Raises:
            FileNotFoundError: Se arquivo de configuração não existe.
        """
        caminho = Path(self._caminho_config)
        if not caminho.exists():
            raise FileNotFoundError(
                f"Arquivo de configuração não encontrado: {self._caminho_config}\n"
                f"Copie config/config_exemplo.json para config/config.json e configure suas credenciais."
            )

        with open(caminho, "r", encoding="utf-8") as f:
            self._config = json.load(f)

        logger.info(f"Configuração carregada de {self._caminho_config}")
        return self._config

    def _criar_cliente(self) -> ClienteOKX:
        """Cria cliente REST da OKX."""
        cfg_okx = self._config.get("okx", {})
        config = ConfiguracaoOKX(
            api_key=cfg_okx.get("api_key", ""),
            secret_key=cfg_okx.get("secret_key", ""),
            passphrase=cfg_okx.get("passphrase", ""),
            demo=cfg_okx.get("demo", True),
        )
        return ClienteOKX(config)

    def _criar_websocket(self) -> WebSocketOKX:
        """Cria cliente WebSocket da OKX."""
        cfg_okx = self._config.get("okx", {})
        return WebSocketOKX(
            api_key=cfg_okx.get("api_key", ""),
            secret_key=cfg_okx.get("secret_key", ""),
            passphrase=cfg_okx.get("passphrase", ""),
            demo=cfg_okx.get("demo", True),
        )

    def _criar_gerenciador_risco(self) -> GerenciadorRisco:
        """Cria gerenciador de risco."""
        cfg_risco = self._config.get("risco", {})
        config = ConfiguracaoRisco(
            tamanho_maximo_ordem=cfg_risco.get("tamanho_maximo_ordem", 0),
            exposicao_maxima=cfg_risco.get("exposicao_maxima", 0),
            stop_loss_percentual=cfg_risco.get("stop_loss_percentual", 2.0),
            stop_loss_diario=cfg_risco.get("stop_loss_diario", 5.0),
            max_ordens_abertas=cfg_risco.get("max_ordens_abertas", 10),
            max_ordens_por_minuto=cfg_risco.get("max_ordens_por_minuto", 30),
            drawdown_maximo=cfg_risco.get("drawdown_maximo", 10.0),
            kill_switch_perda=cfg_risco.get("kill_switch_perda", 15.0),
        )
        return GerenciadorRisco(config)

    def _criar_estrategia(self) -> EstrategiaBase:
        """Cria e configura a estratégia de trading."""
        cfg_estrategia = self._config.get("estrategia", {})
        tipo = cfg_estrategia.get("tipo", "market_making")
        par = cfg_estrategia.get("par", "BTC-USDT")
        intervalo = cfg_estrategia.get("intervalo_ciclo", 1.0)

        modo_str = cfg_estrategia.get("modo_trade", "cash")
        modo_trade = ModoTrade(modo_str)
        self._gerenciador_ordens = GerenciadorOrdens(self._cliente, modo_trade)

        if tipo == "market_making":
            cfg_mm = cfg_estrategia.get("market_making", {})
            config = ConfigMarketMaking(
                spread_bid=cfg_mm.get("spread_bid", 0.001),
                spread_ask=cfg_mm.get("spread_ask", 0.001),
                tamanho_ordem=cfg_mm.get("tamanho_ordem", 0.001),
                num_niveis=cfg_mm.get("num_niveis", 3),
                incremento_nivel=cfg_mm.get("incremento_nivel", 0.0005),
                rebalancear_a_cada=cfg_mm.get("rebalancear_a_cada", 5),
                inventario_maximo=cfg_mm.get("inventario_maximo", 0),
                casas_preco=cfg_mm.get("casas_preco", 2),
                casas_quantidade=cfg_mm.get("casas_quantidade", 6),
                ajuste_inventario=cfg_mm.get("ajuste_inventario", True),
                fator_ajuste=cfg_mm.get("fator_ajuste", 0.5),
            )
            return EstrategiaMarketMaking(
                cliente=self._cliente,
                gerenciador_ordens=self._gerenciador_ordens,
                gerenciador_risco=self._gerenciador_risco,
                par=par,
                config=config,
                intervalo_ciclo=intervalo,
            )

        elif tipo == "grid_trading":
            cfg_grid = cfg_estrategia.get("grid_trading", {})
            config = ConfigGrid(
                preco_minimo=cfg_grid.get("preco_minimo", 0),
                preco_maximo=cfg_grid.get("preco_maximo", 0),
                num_grades=cfg_grid.get("num_grades", 10),
                tamanho_ordem=cfg_grid.get("tamanho_ordem", 0.001),
                grade_geometrica=cfg_grid.get("grade_geometrica", False),
                casas_preco=cfg_grid.get("casas_preco", 2),
                casas_quantidade=cfg_grid.get("casas_quantidade", 6),
                recriar_ordens_preenchidas=cfg_grid.get("recriar_ordens_preenchidas", True),
            )
            return EstrategiaGridTrading(
                cliente=self._cliente,
                gerenciador_ordens=self._gerenciador_ordens,
                gerenciador_risco=self._gerenciador_risco,
                par=par,
                config=config,
                intervalo_ciclo=intervalo,
            )

        else:
            raise ValueError(f"Tipo de estratégia desconhecido: {tipo}")

    async def _callback_ticker(self, dados: dict):
        """Callback para atualizações de ticker via WebSocket."""
        if self._estrategia and dados.get("data"):
            for ticker_data in dados["data"]:
                self._estrategia.atualizar_ticker(ticker_data)

    async def _callback_ordens(self, dados: dict):
        """Callback para atualizações de ordens via WebSocket."""
        if self._estrategia and dados.get("data"):
            for ordem_data in dados["data"]:
                self._estrategia.ao_atualizar_ordem(ordem_data)

    async def _callback_conta(self, dados: dict):
        """Callback para atualizações de saldo via WebSocket."""
        if dados.get("data") and self._gerenciador_risco:
            for conta_data in dados["data"]:
                total = float(conta_data.get("totalEq", 0))
                if total > 0:
                    self._gerenciador_risco.atualizar_capital(total)

    async def iniciar(self):
        """
        Inicia o bot de trading.

        Carrega configuração, conecta à exchange e inicia a estratégia.
        """
        logger.info("=" * 60)
        logger.info("  BOT DE TRADING OKX - INICIANDO")
        logger.info("=" * 60)

        # Carregar configuração
        self.carregar_configuracao()

        # Criar componentes
        self._cliente = self._criar_cliente()
        self._gerenciador_risco = self._criar_gerenciador_risco()

        # Verificar conexão e saldo
        try:
            saldos = self._cliente.obter_saldo()
            capital_total = sum(float(s.get("eq", 0)) for s in saldos)
            self._gerenciador_risco.inicializar(capital_total)
            logger.info(f"Capital total: {capital_total}")
        except Exception as e:
            logger.error(f"Erro ao conectar com a OKX: {e}")
            logger.info("Continuando em modo offline para teste...")
            self._gerenciador_risco.inicializar(0)

        # Criar estratégia
        self._estrategia = self._criar_estrategia()
        par = self._estrategia.par

        # Configurar WebSocket
        self._websocket = self._criar_websocket()
        self._websocket.registrar_callback("tickers", self._callback_ticker)
        self._websocket.registrar_callback("orders", self._callback_ordens)
        self._websocket.registrar_callback("account", self._callback_conta)

        # Canais para assinar
        canais_publicos = [
            AssinaturaCanal(canal="tickers", par=par),
            AssinaturaCanal(canal="books5", par=par),
        ]
        canais_privados = [
            AssinaturaCanal(canal="orders", args_extra={"instType": "SPOT"}),
            AssinaturaCanal(canal="account"),
        ]

        self._rodando = True

        # Iniciar WebSocket
        try:
            await self._websocket.iniciar(
                canais_publicos=canais_publicos,
                canais_privados=canais_privados,
            )
        except Exception as e:
            logger.warning(f"WebSocket não conectado: {e}. Usando polling REST.")

        # Iniciar estratégia
        self._estrategia.iniciar()

        logger.info(f"Bot iniciado com estratégia '{self._estrategia.nome}' no par {par}")

        # Loop principal
        try:
            await self._estrategia.loop_principal()
        except asyncio.CancelledError:
            logger.info("Bot cancelado pelo usuário")
        finally:
            await self.parar()

    async def parar(self):
        """Para o bot e todos os componentes."""
        logger.info("Parando bot de trading...")
        self._rodando = False

        if self._estrategia:
            self._estrategia.parar()

        if self._websocket:
            await self._websocket.parar()

        # Relatório final
        if self._gerenciador_risco:
            relatorio = self._gerenciador_risco.obter_relatorio()
            logger.info("=" * 60)
            logger.info("  RELATÓRIO FINAL")
            logger.info("=" * 60)
            logger.info(f"  PnL Total: {relatorio['pnl_total']:+.4f}")
            logger.info(f"  PnL Diário: {relatorio['pnl_diario']:+.4f}")
            logger.info(f"  Drawdown Atual: {relatorio['drawdown_atual_pct']:.2f}%")
            logger.info("=" * 60)

        if self._gerenciador_ordens:
            resumo = self._gerenciador_ordens.obter_resumo()
            logger.info(f"  Ordens: {resumo}")

        logger.info("Bot parado com sucesso")


def executar():
    """Função principal para executar o bot."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Bot de Trading OKX",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos de uso:
  python -m bot.main --config config/config.json
  python -m bot.main --config config/config.json --debug
  python -m bot.main --demo

Para começar:
  1. Copie config/config_exemplo.json para config/config.json
  2. Configure suas credenciais da API OKX
  3. Execute o bot com o comando acima
        """,
    )

    parser.add_argument(
        "--config", "-c",
        default="config/config.json",
        help="Caminho para arquivo de configuração (padrão: config/config.json)",
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Ativar modo debug com logs detalhados",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Forçar modo demo (trading simulado)",
    )

    args = parser.parse_args()

    if args.debug:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)

    bot = BotTrading(caminho_config=args.config)

    # Tratar sinais para parada limpa
    loop = asyncio.new_event_loop()

    def handler_sinal(sig, frame):
        logger.info(f"Sinal {sig} recebido. Encerrando...")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    signal.signal(signal.SIGINT, handler_sinal)
    signal.signal(signal.SIGTERM, handler_sinal)

    try:
        loop.run_until_complete(bot.iniciar())
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuário (Ctrl+C)")
        loop.run_until_complete(bot.parar())
    finally:
        loop.close()


if __name__ == "__main__":
    executar()
