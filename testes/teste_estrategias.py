"""
Testes unitários para as estratégias de trading.
"""

import unittest
from unittest.mock import patch, MagicMock

from bot.cliente_okx import ClienteOKX, ConfiguracaoOKX, LadoOrdem, ModoTrade
from bot.gerenciador_ordens import GerenciadorOrdens
from bot.gerenciador_risco import GerenciadorRisco, ConfiguracaoRisco
from bot.estrategias.base import TickerAtual
from bot.estrategias.market_making import EstrategiaMarketMaking, ConfigMarketMaking
from bot.estrategias.grid_trading import EstrategiaGridTrading, ConfigGrid


class TesteEstrategiaMarketMaking(unittest.TestCase):
    """Testes para estratégia de Market Making."""

    def setUp(self):
        self.config_okx = ConfiguracaoOKX(
            api_key="test", secret_key="test", passphrase="test", demo=True
        )
        self.cliente = ClienteOKX(self.config_okx)
        self.gerenciador_ordens = GerenciadorOrdens(self.cliente)
        self.config_risco = ConfiguracaoRisco(
            tamanho_maximo_ordem=1000,
            max_ordens_abertas=20,
            max_ordens_por_minuto=60,
        )
        self.gerenciador_risco = GerenciadorRisco(self.config_risco)
        self.gerenciador_risco.inicializar(10000)

        self.config_mm = ConfigMarketMaking(
            spread_bid=0.001,
            spread_ask=0.001,
            tamanho_ordem=0.001,
            num_niveis=2,
            rebalancear_a_cada=3,
        )

        self.estrategia = EstrategiaMarketMaking(
            cliente=self.cliente,
            gerenciador_ordens=self.gerenciador_ordens,
            gerenciador_risco=self.gerenciador_risco,
            par="BTC-USDT",
            config=self.config_mm,
        )

    def teste_calcular_mid_price(self):
        ticker = TickerAtual(
            par="BTC-USDT",
            ultimo_preco=95000,
            melhor_bid=94999,
            melhor_ask=95001,
        )
        mid = self.estrategia._calcular_mid_price(ticker)
        self.assertEqual(mid, 95000.0)

    def teste_mid_price_sem_bid_ask(self):
        ticker = TickerAtual(
            par="BTC-USDT",
            ultimo_preco=95000,
            melhor_bid=0,
            melhor_ask=0,
        )
        mid = self.estrategia._calcular_mid_price(ticker)
        self.assertEqual(mid, 95000.0)

    def teste_ajuste_inventario(self):
        self.estrategia._inventario = 0
        bid, ask = self.estrategia._ajustar_spread_por_inventario(0.001, 0.001)
        self.assertEqual(bid, 0.001)
        self.assertEqual(ask, 0.001)

        # Com inventário positivo (comprado demais)
        self.estrategia._inventario = 10
        bid, ask = self.estrategia._ajustar_spread_por_inventario(0.001, 0.001)
        self.assertGreater(bid, 0.001)  # Spread de compra aumenta

    def teste_iniciar_parar(self):
        self.estrategia.iniciar()
        self.assertTrue(self.estrategia.ativa)

        self.estrategia.parar()
        self.assertFalse(self.estrategia.ativa)

    def teste_atualizar_ticker(self):
        dados = {
            "instId": "BTC-USDT",
            "last": "95000",
            "bidPx": "94999",
            "askPx": "95001",
            "vol24h": "1000",
        }
        self.estrategia.atualizar_ticker(dados)
        status = self.estrategia.obter_status()
        self.assertEqual(status["ultimo_preco"], 95000.0)

    def teste_ao_atualizar_ordem_compra(self):
        self.estrategia.ao_atualizar_ordem({
            "clOrdId": "test",
            "ordId": "123",
            "state": "filled",
            "side": "buy",
            "accFillSz": "0.001",
            "avgPx": "95000",
        })
        self.assertAlmostEqual(self.estrategia._inventario, 0.001)

    def teste_ao_atualizar_ordem_venda(self):
        self.estrategia.ao_atualizar_ordem({
            "clOrdId": "test",
            "ordId": "123",
            "state": "filled",
            "side": "sell",
            "accFillSz": "0.001",
            "avgPx": "95000",
        })
        self.assertAlmostEqual(self.estrategia._inventario, -0.001)

    def teste_kill_switch_bloqueia_ciclo(self):
        self.gerenciador_risco._estado.kill_switch_ativado = True
        ticker = TickerAtual(par="BTC-USDT", ultimo_preco=95000)
        # Não deve lançar exceção
        self.estrategia.executar_ciclo(ticker)


class TesteEstrategiaGridTrading(unittest.TestCase):
    """Testes para estratégia de Grid Trading."""

    def setUp(self):
        self.config_okx = ConfiguracaoOKX(
            api_key="test", secret_key="test", passphrase="test", demo=True
        )
        self.cliente = ClienteOKX(self.config_okx)
        self.gerenciador_ordens = GerenciadorOrdens(self.cliente)
        self.config_risco = ConfiguracaoRisco(
            tamanho_maximo_ordem=1000,
            max_ordens_abertas=50,
            max_ordens_por_minuto=60,
        )
        self.gerenciador_risco = GerenciadorRisco(self.config_risco)
        self.gerenciador_risco.inicializar(10000)

        self.config_grid = ConfigGrid(
            preco_minimo=90000,
            preco_maximo=100000,
            num_grades=10,
            tamanho_ordem=0.001,
        )

        self.estrategia = EstrategiaGridTrading(
            cliente=self.cliente,
            gerenciador_ordens=self.gerenciador_ordens,
            gerenciador_risco=self.gerenciador_risco,
            par="BTC-USDT",
            config=self.config_grid,
        )

    def teste_calcular_intervalo_linear(self):
        intervalo = self.estrategia._calcular_intervalo()
        self.assertEqual(intervalo, 1000.0)  # (100000-90000)/10

    def teste_calcular_intervalo_geometrico(self):
        self.estrategia._config.grade_geometrica = True
        intervalo = self.estrategia._calcular_intervalo()
        self.assertGreater(intervalo, 0)

    def teste_calcular_niveis(self):
        self.estrategia._calcular_niveis()
        self.assertEqual(len(self.estrategia._niveis), 11)  # num_grades + 1

        # Verificar primeiro e último nível
        self.assertAlmostEqual(self.estrategia._niveis[0].preco, 90000)
        self.assertAlmostEqual(self.estrategia._niveis[10].preco, 100000)

    def teste_configuracao_invalida_preco(self):
        self.estrategia._config.preco_minimo = 0
        self.estrategia.ao_iniciar()
        self.assertFalse(self.estrategia.ativa)

    def teste_configuracao_preco_invertido(self):
        self.estrategia._config.preco_minimo = 100000
        self.estrategia._config.preco_maximo = 90000
        self.estrategia.ao_iniciar()
        self.assertFalse(self.estrategia.ativa)

    def teste_status_grade(self):
        self.estrategia._calcular_niveis()
        status = self.estrategia.obter_status_grade()

        self.assertEqual(status["par"], "BTC-USDT")
        self.assertEqual(status["preco_minimo"], 90000)
        self.assertEqual(status["preco_maximo"], 100000)
        self.assertEqual(status["num_grades"], 10)
        self.assertFalse(status["grade_inicializada"])

    def teste_kill_switch_bloqueia_ciclo(self):
        self.gerenciador_risco._estado.kill_switch_ativado = True
        ticker = TickerAtual(par="BTC-USDT", ultimo_preco=95000)
        self.estrategia.executar_ciclo(ticker)
        self.assertFalse(self.estrategia._grade_inicializada)


if __name__ == "__main__":
    unittest.main()
