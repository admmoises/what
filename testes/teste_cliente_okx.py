"""
Testes unitários para o cliente REST da OKX.
"""

import hashlib
import hmac
import base64
import json
import unittest
from unittest.mock import patch, MagicMock
from decimal import Decimal

from bot.cliente_okx import (
    ClienteOKX,
    ConfiguracaoOKX,
    TipoOrdem,
    LadoOrdem,
    ModoTrade,
)
from bot.gerenciador_risco import GerenciadorRisco, ConfiguracaoRisco
from bot.gerenciador_ordens import GerenciadorOrdens, StatusOrdem
from bot.utils.helpers import (
    formatar_preco,
    formatar_quantidade,
    calcular_preco_medio,
    calcular_variacao_percentual,
    timestamp_iso,
)


class TesteHelpers(unittest.TestCase):
    """Testes para funções auxiliares."""

    def teste_formatar_preco(self):
        self.assertEqual(formatar_preco(100.12345, 2), "100.12")
        self.assertEqual(formatar_preco(100.999, 2), "100.99")
        self.assertEqual(formatar_preco("50.5", 1), "50.5")

    def teste_formatar_quantidade(self):
        self.assertEqual(formatar_quantidade(0.123456789, 6), "0.123456")
        self.assertEqual(formatar_quantidade(1.5, 2), "1.50")

    def teste_calcular_preco_medio(self):
        self.assertEqual(calcular_preco_medio([100, 200, 300]), 200.0)
        self.assertEqual(calcular_preco_medio([100, 200], [1, 3]), 175.0)
        self.assertEqual(calcular_preco_medio([]), 0.0)

    def teste_calcular_variacao_percentual(self):
        self.assertAlmostEqual(calcular_variacao_percentual(100, 110), 10.0)
        self.assertAlmostEqual(calcular_variacao_percentual(100, 90), -10.0)
        self.assertEqual(calcular_variacao_percentual(0, 100), 0.0)

    def teste_timestamp_iso(self):
        ts = timestamp_iso()
        self.assertTrue(ts.endswith("Z"))
        self.assertIn("T", ts)


class TesteConfiguracaoOKX(unittest.TestCase):
    """Testes para configuração da OKX."""

    def teste_base_url(self):
        config = ConfiguracaoOKX(
            api_key="test", secret_key="test", passphrase="test"
        )
        self.assertEqual(config.base_url, "https://www.okx.com")

    def teste_modo_demo(self):
        config = ConfiguracaoOKX(
            api_key="test", secret_key="test", passphrase="test", demo=True
        )
        self.assertTrue(config.demo)


class TesteClienteOKXAssinatura(unittest.TestCase):
    """Testes para o mecanismo de assinatura do cliente OKX."""

    def setUp(self):
        self.config = ConfiguracaoOKX(
            api_key="test-key",
            secret_key="test-secret",
            passphrase="test-pass",
        )
        self.cliente = ClienteOKX(self.config)

    def teste_assinatura(self):
        timestamp = "2024-01-01T00:00:00.000Z"
        metodo = "GET"
        caminho = "/api/v5/account/balance"

        assinatura = self.cliente._assinar(timestamp, metodo, caminho)

        # Verificar que a assinatura é base64 válida
        self.assertIsInstance(assinatura, str)
        decoded = base64.b64decode(assinatura)
        self.assertEqual(len(decoded), 32)  # SHA256 = 32 bytes

    def teste_assinatura_com_corpo(self):
        timestamp = "2024-01-01T00:00:00.000Z"
        metodo = "POST"
        caminho = "/api/v5/trade/order"
        corpo = '{"instId":"BTC-USDT","side":"buy"}'

        assinatura = self.cliente._assinar(timestamp, metodo, caminho, corpo)
        self.assertIsInstance(assinatura, str)

    def teste_assinaturas_diferentes(self):
        ts = "2024-01-01T00:00:00.000Z"
        ass1 = self.cliente._assinar(ts, "GET", "/api/v5/account/balance")
        ass2 = self.cliente._assinar(ts, "POST", "/api/v5/trade/order")
        self.assertNotEqual(ass1, ass2)


class TesteClienteOKXEndpoints(unittest.TestCase):
    """Testes para endpoints do cliente OKX com mocks."""

    def setUp(self):
        self.config = ConfiguracaoOKX(
            api_key="test-key",
            secret_key="test-secret",
            passphrase="test-pass",
            demo=True,
        )
        self.cliente = ClienteOKX(self.config)

    @patch("bot.cliente_okx.requests.Session.get")
    def teste_obter_ticker(self, mock_get):
        mock_resposta = MagicMock()
        mock_resposta.json.return_value = {
            "code": "0",
            "data": [
                {
                    "instId": "BTC-USDT",
                    "last": "95000.5",
                    "bidPx": "95000.0",
                    "askPx": "95001.0",
                    "vol24h": "1000",
                }
            ],
        }
        mock_resposta.raise_for_status = MagicMock()
        mock_get.return_value = mock_resposta

        ticker = self.cliente.obter_ticker("BTC-USDT")

        self.assertEqual(ticker["instId"], "BTC-USDT")
        self.assertEqual(ticker["last"], "95000.5")

    @patch("bot.cliente_okx.requests.Session.get")
    def teste_obter_saldo(self, mock_get):
        mock_resposta = MagicMock()
        mock_resposta.json.return_value = {
            "code": "0",
            "data": [
                {
                    "details": [
                        {"ccy": "USDT", "availBal": "1000", "frozenBal": "0"},
                        {"ccy": "BTC", "availBal": "0.5", "frozenBal": "0.01"},
                    ]
                }
            ],
        }
        mock_resposta.raise_for_status = MagicMock()
        mock_get.return_value = mock_resposta

        saldos = self.cliente.obter_saldo()

        self.assertEqual(len(saldos), 2)
        self.assertEqual(saldos[0]["ccy"], "USDT")

    @patch("bot.cliente_okx.requests.Session.post")
    def teste_criar_ordem(self, mock_post):
        mock_resposta = MagicMock()
        mock_resposta.json.return_value = {
            "code": "0",
            "data": [
                {"ordId": "123456", "clOrdId": "bot_1", "sCode": "0", "sMsg": ""}
            ],
        }
        mock_resposta.raise_for_status = MagicMock()
        mock_post.return_value = mock_resposta

        resultado = self.cliente.criar_ordem(
            par="BTC-USDT",
            lado=LadoOrdem.COMPRA,
            tipo=TipoOrdem.LIMITE,
            quantidade="0.001",
            preco="95000",
        )

        self.assertEqual(resultado["ordId"], "123456")
        self.assertEqual(resultado["sCode"], "0")

    @patch("bot.cliente_okx.requests.Session.post")
    def teste_cancelar_ordem(self, mock_post):
        mock_resposta = MagicMock()
        mock_resposta.json.return_value = {
            "code": "0",
            "data": [{"ordId": "123456", "sCode": "0", "sMsg": ""}],
        }
        mock_resposta.raise_for_status = MagicMock()
        mock_post.return_value = mock_resposta

        resultado = self.cliente.cancelar_ordem("BTC-USDT", "123456")
        self.assertEqual(resultado["sCode"], "0")


class TesteGerenciadorRisco(unittest.TestCase):
    """Testes para o gerenciador de risco."""

    def setUp(self):
        self.config = ConfiguracaoRisco(
            tamanho_maximo_ordem=100,
            stop_loss_percentual=2.0,
            stop_loss_diario=5.0,
            max_ordens_abertas=5,
            max_ordens_por_minuto=10,
            drawdown_maximo=10.0,
            kill_switch_perda=15.0,
        )
        self.risco = GerenciadorRisco(self.config)
        self.risco.inicializar(10000)

    def teste_inicializacao(self):
        self.assertEqual(self.risco.estado.capital_inicial, 10000)
        self.assertEqual(self.risco.estado.capital_atual, 10000)
        self.assertFalse(self.risco.kill_switch_ativo)

    def teste_pode_criar_ordem_ok(self):
        permitido, motivo = self.risco.pode_criar_ordem(50, 0)
        self.assertTrue(permitido)
        self.assertEqual(motivo, "OK")

    def teste_ordem_excede_tamanho_maximo(self):
        permitido, motivo = self.risco.pode_criar_ordem(150, 0)
        self.assertFalse(permitido)
        self.assertIn("Tamanho", motivo)

    def teste_limite_ordens_abertas(self):
        permitido, motivo = self.risco.pode_criar_ordem(50, 5)
        self.assertFalse(permitido)
        self.assertIn("ordens abertas", motivo)

    def teste_kill_switch(self):
        # Simular perda de 16%
        self.risco.atualizar_capital(8400)
        self.assertTrue(self.risco.kill_switch_ativo)

        permitido, motivo = self.risco.pode_criar_ordem(50, 0)
        self.assertFalse(permitido)
        self.assertIn("Kill switch", motivo)

    def teste_registrar_pnl(self):
        self.risco.registrar_pnl(100)
        self.assertEqual(self.risco.estado.pnl_diario, 100)
        self.assertEqual(self.risco.estado.capital_atual, 10100)

        self.risco.registrar_pnl(-50)
        self.assertEqual(self.risco.estado.pnl_diario, 50)

    def teste_drawdown(self):
        self.risco.atualizar_capital(10500)  # Novo pico
        self.assertEqual(self.risco.estado.pico_capital, 10500)

        self.risco.atualizar_capital(9500)  # Drawdown
        drawdown = self.risco.estado.drawdown_atual
        self.assertAlmostEqual(drawdown, 9.52, places=1)

    def teste_stop_loss_ordem(self):
        # Compra
        atingido = self.risco.verificar_stop_loss_ordem(100, 97.5, "buy")
        self.assertTrue(atingido)

        nao_atingido = self.risco.verificar_stop_loss_ordem(100, 99, "buy")
        self.assertFalse(nao_atingido)

    def teste_resetar_pnl_diario(self):
        self.risco.registrar_pnl(500)
        self.risco.resetar_pnl_diario()
        self.assertEqual(self.risco.estado.pnl_diario, 0)

    def teste_relatorio(self):
        self.risco.registrar_pnl(100)
        relatorio = self.risco.obter_relatorio()
        self.assertIn("capital_inicial", relatorio)
        self.assertIn("pnl_total", relatorio)
        self.assertIn("kill_switch", relatorio)


class TesteGerenciadorOrdens(unittest.TestCase):
    """Testes para o gerenciador de ordens."""

    def setUp(self):
        self.config = ConfiguracaoOKX(
            api_key="test", secret_key="test", passphrase="test", demo=True
        )
        self.cliente = ClienteOKX(self.config)
        self.gerenciador = GerenciadorOrdens(self.cliente)

    def teste_gerar_id_cliente(self):
        id1 = self.gerenciador._gerar_id_cliente()
        id2 = self.gerenciador._gerar_id_cliente()
        self.assertNotEqual(id1, id2)
        self.assertTrue(id1.startswith("bot_"))

    @patch("bot.cliente_okx.requests.Session.post")
    def teste_criar_ordem_limite(self, mock_post):
        mock_resposta = MagicMock()
        mock_resposta.json.return_value = {
            "code": "0",
            "data": [{"ordId": "123", "sCode": "0", "sMsg": ""}],
        }
        mock_resposta.raise_for_status = MagicMock()
        mock_post.return_value = mock_resposta

        ordem = self.gerenciador.criar_ordem_limite(
            par="BTC-USDT",
            lado=LadoOrdem.COMPRA,
            preco=95000.0,
            quantidade=0.001,
        )

        self.assertEqual(ordem.status, StatusOrdem.ABERTA)
        self.assertEqual(ordem.id_exchange, "123")
        self.assertEqual(len(self.gerenciador.ordens_ativas), 1)

    def teste_ordens_ativas_filtro(self):
        # Sem mock - testar propriedades
        self.assertEqual(len(self.gerenciador.ordens_ativas), 0)
        self.assertEqual(len(self.gerenciador.ordens_compra_ativas), 0)
        self.assertEqual(len(self.gerenciador.ordens_venda_ativas), 0)

    def teste_resumo(self):
        resumo = self.gerenciador.obter_resumo()
        self.assertEqual(resumo["total"], 0)
        self.assertEqual(resumo["ativas"], 0)

    def teste_atualizar_ordem(self):
        from bot.gerenciador_ordens import OrdemLocal

        ordem = OrdemLocal(
            id_cliente="test_1",
            par="BTC-USDT",
            lado=LadoOrdem.COMPRA,
            tipo=TipoOrdem.LIMITE,
            quantidade="0.001",
            preco="95000",
            id_exchange="ex_123",
            status=StatusOrdem.ABERTA,
        )
        self.gerenciador._ordens["test_1"] = ordem

        self.gerenciador.atualizar_ordem({
            "clOrdId": "test_1",
            "ordId": "ex_123",
            "state": "filled",
            "accFillSz": "0.001",
            "avgPx": "95000",
        })

        self.assertEqual(ordem.status, StatusOrdem.PREENCHIDA)
        self.assertEqual(ordem.quantidade_preenchida, "0.001")


if __name__ == "__main__":
    unittest.main()
