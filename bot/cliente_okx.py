"""
Cliente REST para a API v5 da OKX.

Implementa autenticação HMAC-SHA256 e métodos para os principais
endpoints de trading, conta e mercado.
"""

import hashlib
import hmac
import base64
import json
import time
from enum import Enum
from dataclasses import dataclass
from typing import Any

import requests

from bot.utils.logger import configurar_logger
from bot.utils.helpers import timestamp_iso

logger = configurar_logger("okx.rest")


class TipoOrdem(str, Enum):
    """Tipos de ordem suportados pela OKX."""
    MERCADO = "market"
    LIMITE = "limit"
    POST_ONLY = "post_only"
    FOK = "fok"  # Fill or Kill
    IOC = "ioc"  # Immediate or Cancel


class LadoOrdem(str, Enum):
    """Lado da ordem (compra/venda)."""
    COMPRA = "buy"
    VENDA = "sell"


class ModoTrade(str, Enum):
    """Modo de trading."""
    SPOT = "cash"
    MARGEM_CRUZADA = "cross"
    MARGEM_ISOLADA = "isolated"


@dataclass
class ConfiguracaoOKX:
    """Configuração de conexão com a OKX."""
    api_key: str
    secret_key: str
    passphrase: str
    demo: bool = False
    timeout: int = 10

    @property
    def base_url(self) -> str:
        return "https://www.okx.com"


class ClienteOKX:
    """
    Cliente para a API REST v5 da OKX.

    Suporta endpoints de mercado (públicos) e de trading/conta (privados).
    """

    def __init__(self, config: ConfiguracaoOKX):
        self._config = config
        self._sessao = requests.Session()
        self._sessao.headers.update({
            "Content-Type": "application/json",
            "OK-ACCESS-KEY": config.api_key,
            "OK-ACCESS-PASSPHRASE": config.passphrase,
        })
        if config.demo:
            self._sessao.headers["x-simulated-trading"] = "1"
            logger.info("Modo DEMO ativado")

    def _assinar(self, timestamp: str, metodo: str, caminho: str, corpo: str = "") -> str:
        """
        Gera assinatura HMAC-SHA256 para autenticação.

        Args:
            timestamp: Timestamp ISO 8601.
            metodo: Método HTTP (GET/POST).
            caminho: Caminho do endpoint.
            corpo: Corpo da requisição (para POST).

        Returns:
            Assinatura codificada em Base64.
        """
        mensagem = timestamp + metodo.upper() + caminho + corpo
        mac = hmac.new(
            self._config.secret_key.encode("utf-8"),
            mensagem.encode("utf-8"),
            hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode("utf-8")

    def _requisicao(
        self,
        metodo: str,
        caminho: str,
        params: dict | None = None,
        dados: dict | None = None,
        privado: bool = True,
    ) -> dict[str, Any]:
        """
        Executa requisição HTTP para a API da OKX.

        Args:
            metodo: GET ou POST.
            caminho: Caminho do endpoint (ex: /api/v5/trade/order).
            params: Parâmetros de query string.
            dados: Corpo da requisição (JSON).
            privado: Se True, adiciona headers de autenticação.

        Returns:
            Resposta da API como dicionário.

        Raises:
            Exception: Se a API retornar erro.
        """
        url = self._config.base_url + caminho

        corpo_str = ""
        if dados:
            corpo_str = json.dumps(dados)

        # Monta query string no caminho para assinatura
        caminho_completo = caminho
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            caminho_completo = f"{caminho}?{query}"

        if privado:
            ts = timestamp_iso()
            assinatura = self._assinar(ts, metodo, caminho_completo, corpo_str)
            self._sessao.headers.update({
                "OK-ACCESS-SIGN": assinatura,
                "OK-ACCESS-TIMESTAMP": ts,
            })

        try:
            if metodo.upper() == "GET":
                resposta = self._sessao.get(url, params=params, timeout=self._config.timeout)
            else:
                resposta = self._sessao.post(url, data=corpo_str, timeout=self._config.timeout)

            resposta.raise_for_status()
            resultado = resposta.json()

            if resultado.get("code") != "0":
                msg_erro = resultado.get("msg", "Erro desconhecido")
                codigo = resultado.get("code", "?")
                logger.error(f"Erro API OKX [{codigo}]: {msg_erro}")
                raise Exception(f"Erro API OKX [{codigo}]: {msg_erro}")

            return resultado

        except requests.exceptions.RequestException as e:
            logger.error(f"Erro de conexão: {e}")
            raise

    # ── Endpoints de Mercado (Públicos) ────────────────────────────

    def obter_ticker(self, par: str) -> dict:
        """
        Obtém dados do ticker para um par de trading.

        Args:
            par: Par de trading (ex: BTC-USDT).

        Returns:
            Dados do ticker incluindo último preço, bid, ask, volume.
        """
        resultado = self._requisicao(
            "GET",
            "/api/v5/market/ticker",
            params={"instId": par},
            privado=False,
        )
        dados = resultado.get("data", [])
        if dados:
            ticker = dados[0]
            logger.debug(
                f"Ticker {par}: último={ticker.get('last')} "
                f"bid={ticker.get('bidPx')} ask={ticker.get('askPx')}"
            )
        return dados[0] if dados else {}

    def obter_livro_ofertas(self, par: str, profundidade: int = 20) -> dict:
        """
        Obtém livro de ofertas (order book).

        Args:
            par: Par de trading.
            profundidade: Número de níveis (1-400).

        Returns:
            Livro de ofertas com bids e asks.
        """
        resultado = self._requisicao(
            "GET",
            "/api/v5/market/books",
            params={"instId": par, "sz": str(profundidade)},
            privado=False,
        )
        return resultado.get("data", [{}])[0] if resultado.get("data") else {}

    def obter_candles(
        self, par: str, intervalo: str = "1H", limite: int = 100
    ) -> list[list]:
        """
        Obtém dados de candlestick.

        Args:
            par: Par de trading.
            intervalo: Intervalo (1m, 5m, 15m, 1H, 4H, 1D, etc).
            limite: Número máximo de candles.

        Returns:
            Lista de candles [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm].
        """
        resultado = self._requisicao(
            "GET",
            "/api/v5/market/candles",
            params={"instId": par, "bar": intervalo, "limit": str(limite)},
            privado=False,
        )
        return resultado.get("data", [])

    # ── Endpoints de Conta (Privados) ──────────────────────────────

    def obter_saldo(self, moeda: str | None = None) -> list[dict]:
        """
        Obtém saldo da conta.

        Args:
            moeda: Filtrar por moeda específica (ex: USDT). None para todas.

        Returns:
            Lista de saldos.
        """
        params = {}
        if moeda:
            params["ccy"] = moeda

        resultado = self._requisicao("GET", "/api/v5/account/balance", params=params or None)
        dados = resultado.get("data", [])
        if dados:
            detalhes = dados[0].get("details", [])
            for d in detalhes:
                logger.info(
                    f"Saldo {d.get('ccy')}: disponível={d.get('availBal')} "
                    f"congelado={d.get('frozenBal')}"
                )
            return detalhes
        return []

    def obter_posicoes(self, par: str | None = None) -> list[dict]:
        """
        Obtém posições abertas.

        Args:
            par: Filtrar por par específico.

        Returns:
            Lista de posições.
        """
        params = {}
        if par:
            params["instId"] = par

        resultado = self._requisicao("GET", "/api/v5/account/positions", params=params or None)
        return resultado.get("data", [])

    # ── Endpoints de Trading (Privados) ────────────────────────────

    def criar_ordem(
        self,
        par: str,
        lado: LadoOrdem,
        tipo: TipoOrdem,
        quantidade: str,
        preco: str | None = None,
        modo_trade: ModoTrade = ModoTrade.SPOT,
        id_cliente: str | None = None,
    ) -> dict:
        """
        Cria uma ordem de trading.

        Args:
            par: Par de trading (ex: BTC-USDT).
            lado: COMPRA ou VENDA.
            tipo: Tipo da ordem (MERCADO, LIMITE, etc).
            quantidade: Quantidade a negociar.
            preco: Preço limite (obrigatório para ordens limite).
            modo_trade: Modo de trading (SPOT, MARGEM_CRUZADA, MARGEM_ISOLADA).
            id_cliente: ID personalizado da ordem.

        Returns:
            Dados da ordem criada.
        """
        dados = {
            "instId": par,
            "tdMode": modo_trade.value,
            "side": lado.value,
            "ordType": tipo.value,
            "sz": quantidade,
        }

        if preco and tipo != TipoOrdem.MERCADO:
            dados["px"] = preco

        if id_cliente:
            dados["clOrdId"] = id_cliente

        logger.info(
            f"Criando ordem: {lado.value} {quantidade} {par} @ "
            f"{'mercado' if tipo == TipoOrdem.MERCADO else preco}"
        )

        resultado = self._requisicao("POST", "/api/v5/trade/order", dados=dados)
        ordens = resultado.get("data", [])

        if ordens:
            ordem = ordens[0]
            if ordem.get("sCode") == "0":
                logger.info(f"Ordem criada com sucesso: ID={ordem.get('ordId')}")
            else:
                logger.error(
                    f"Falha ao criar ordem: [{ordem.get('sCode')}] {ordem.get('sMsg')}"
                )

        return ordens[0] if ordens else {}

    def cancelar_ordem(self, par: str, id_ordem: str) -> dict:
        """
        Cancela uma ordem.

        Args:
            par: Par de trading.
            id_ordem: ID da ordem a cancelar.

        Returns:
            Resultado do cancelamento.
        """
        logger.info(f"Cancelando ordem {id_ordem} para {par}")
        resultado = self._requisicao(
            "POST",
            "/api/v5/trade/cancel-order",
            dados={"instId": par, "ordId": id_ordem},
        )
        return resultado.get("data", [{}])[0] if resultado.get("data") else {}

    def cancelar_todas_ordens(self, par: str) -> list[dict]:
        """
        Cancela todas as ordens pendentes de um par.

        Args:
            par: Par de trading.

        Returns:
            Lista de resultados de cancelamento.
        """
        ordens_abertas = self.obter_ordens_abertas(par)
        resultados = []
        for ordem in ordens_abertas:
            resultado = self.cancelar_ordem(par, ordem["ordId"])
            resultados.append(resultado)

        logger.info(f"Canceladas {len(resultados)} ordens para {par}")
        return resultados

    def obter_ordem(self, par: str, id_ordem: str) -> dict:
        """
        Obtém detalhes de uma ordem.

        Args:
            par: Par de trading.
            id_ordem: ID da ordem.

        Returns:
            Detalhes da ordem.
        """
        resultado = self._requisicao(
            "GET",
            "/api/v5/trade/order",
            params={"instId": par, "ordId": id_ordem},
        )
        return resultado.get("data", [{}])[0] if resultado.get("data") else {}

    def obter_ordens_abertas(self, par: str | None = None) -> list[dict]:
        """
        Obtém ordens abertas/pendentes.

        Args:
            par: Filtrar por par específico.

        Returns:
            Lista de ordens abertas.
        """
        params = {}
        if par:
            params["instId"] = par

        resultado = self._requisicao(
            "GET", "/api/v5/trade/orders-pending", params=params or None
        )
        return resultado.get("data", [])

    def obter_historico_ordens(self, par: str, tipo_inst: str = "SPOT", limite: int = 50) -> list[dict]:
        """
        Obtém histórico de ordens.

        Args:
            par: Par de trading.
            tipo_inst: Tipo de instrumento (SPOT, MARGIN, SWAP, FUTURES).
            limite: Número máximo de ordens.

        Returns:
            Lista de ordens históricas.
        """
        resultado = self._requisicao(
            "GET",
            "/api/v5/trade/orders-history-archive",
            params={"instId": par, "instType": tipo_inst, "limit": str(limite)},
        )
        return resultado.get("data", [])
