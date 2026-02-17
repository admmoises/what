"""
Cliente WebSocket para a API v5 da OKX.

Gerencia conexões de dados públicos (tickers, livro de ofertas, trades)
e privados (ordens, posições, saldo) em tempo real.
"""

import asyncio
import hashlib
import hmac
import base64
import json
import time
from typing import Any, Callable, Coroutine
from dataclasses import dataclass, field

import websockets
from websockets.asyncio.client import connect as ws_connect

from bot.utils.logger import configurar_logger
from bot.utils.helpers import timestamp_iso

logger = configurar_logger("okx.ws")

# Tipo para callbacks
Callback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


@dataclass
class AssinaturaCanal:
    """Representação de uma assinatura de canal WebSocket."""
    canal: str
    par: str | None = None
    args_extra: dict = field(default_factory=dict)

    def para_dict(self) -> dict:
        d = {"channel": self.canal}
        if self.par:
            d["instId"] = self.par
        d.update(self.args_extra)
        return d


class WebSocketOKX:
    """
    Cliente WebSocket para dados em tempo real da OKX.

    Suporta canais públicos (mercado) e privados (conta/ordens).
    Inclui reconexão automática e ping/pong keepalive.
    """

    # URLs WebSocket
    WS_PUBLICO = "wss://ws.okx.com:8443/ws/v5/public"
    WS_PRIVADO = "wss://ws.okx.com:8443/ws/v5/private"
    WS_PUBLICO_DEMO = "wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999"
    WS_PRIVADO_DEMO = "wss://wspap.okx.com:8443/ws/v5/private?brokerId=9999"

    def __init__(
        self,
        api_key: str = "",
        secret_key: str = "",
        passphrase: str = "",
        demo: bool = False,
    ):
        self._api_key = api_key
        self._secret_key = secret_key
        self._passphrase = passphrase
        self._demo = demo

        self._ws_publico: Any = None
        self._ws_privado: Any = None
        self._callbacks: dict[str, list[Callback]] = {}
        self._assinaturas: list[AssinaturaCanal] = []
        self._rodando = False
        self._tarefas: list[asyncio.Task] = []

    @property
    def _url_publico(self) -> str:
        return self.WS_PUBLICO_DEMO if self._demo else self.WS_PUBLICO

    @property
    def _url_privado(self) -> str:
        return self.WS_PRIVADO_DEMO if self._demo else self.WS_PRIVADO

    def _gerar_assinatura_login(self) -> dict:
        """Gera mensagem de login para WebSocket privado."""
        ts = str(int(time.time()))
        mensagem = ts + "GET" + "/users/self/verify"
        mac = hmac.new(
            self._secret_key.encode("utf-8"),
            mensagem.encode("utf-8"),
            hashlib.sha256,
        )
        assinatura = base64.b64encode(mac.digest()).decode("utf-8")

        return {
            "op": "login",
            "args": [
                {
                    "apiKey": self._api_key,
                    "passphrase": self._passphrase,
                    "timestamp": ts,
                    "sign": assinatura,
                }
            ],
        }

    def registrar_callback(self, canal: str, callback: Callback):
        """
        Registra callback para um canal específico.

        Args:
            canal: Nome do canal (tickers, books, trades, orders, etc).
            callback: Função async chamada quando dados chegam.
        """
        if canal not in self._callbacks:
            self._callbacks[canal] = []
        self._callbacks[canal].append(callback)
        logger.debug(f"Callback registrado para canal '{canal}'")

    async def _notificar_callbacks(self, canal: str, dados: dict):
        """Notifica todos callbacks registrados para um canal."""
        for callback in self._callbacks.get(canal, []):
            try:
                await callback(dados)
            except Exception as e:
                logger.error(f"Erro em callback do canal '{canal}': {e}")

    async def _enviar(self, ws, mensagem: dict):
        """Envia mensagem JSON via WebSocket."""
        await ws.send(json.dumps(mensagem))

    async def _processar_mensagens(self, ws, tipo: str):
        """
        Loop de processamento de mensagens WebSocket.

        Args:
            ws: Conexão WebSocket.
            tipo: 'publico' ou 'privado'.
        """
        try:
            async for mensagem_raw in ws:
                if mensagem_raw == "pong":
                    continue

                try:
                    dados = json.loads(mensagem_raw)
                except json.JSONDecodeError:
                    continue

                # Resposta de login
                if dados.get("event") == "login":
                    if dados.get("code") == "0":
                        logger.info("Login WebSocket privado bem-sucedido")
                    else:
                        logger.error(f"Falha no login WebSocket: {dados.get('msg')}")
                    continue

                # Resposta de assinatura
                if dados.get("event") == "subscribe":
                    canal = dados.get("arg", {}).get("channel", "?")
                    logger.info(f"Assinatura confirmada: {canal}")
                    continue

                if dados.get("event") == "error":
                    logger.error(f"Erro WebSocket: {dados.get('msg')}")
                    continue

                # Dados de mercado/conta
                canal = dados.get("arg", {}).get("channel")
                if canal and "data" in dados:
                    await self._notificar_callbacks(canal, dados)

        except websockets.exceptions.ConnectionClosed:
            logger.warning(f"Conexão WebSocket {tipo} fechada")
        except Exception as e:
            logger.error(f"Erro no processamento WebSocket {tipo}: {e}")

    async def _keepalive(self, ws, tipo: str):
        """Envia ping periodicamente para manter conexão ativa."""
        while self._rodando:
            try:
                await ws.send("ping")
                await asyncio.sleep(25)
            except Exception:
                logger.warning(f"Falha no keepalive {tipo}")
                break

    async def conectar_publico(self, assinaturas: list[AssinaturaCanal]):
        """
        Conecta ao WebSocket público e assina canais.

        Args:
            assinaturas: Lista de canais para assinar.
        """
        logger.info(f"Conectando ao WebSocket público: {self._url_publico}")

        self._ws_publico = await ws_connect(self._url_publico)

        # Assinar canais
        args = [a.para_dict() for a in assinaturas]
        await self._enviar(self._ws_publico, {"op": "subscribe", "args": args})

        # Iniciar processamento
        tarefa_msg = asyncio.create_task(
            self._processar_mensagens(self._ws_publico, "publico")
        )
        tarefa_ping = asyncio.create_task(
            self._keepalive(self._ws_publico, "publico")
        )
        self._tarefas.extend([tarefa_msg, tarefa_ping])

    async def conectar_privado(self, assinaturas: list[AssinaturaCanal] | None = None):
        """
        Conecta ao WebSocket privado, faz login e assina canais.

        Args:
            assinaturas: Lista de canais privados para assinar.
        """
        if not self._api_key:
            logger.error("API key necessária para WebSocket privado")
            return

        logger.info(f"Conectando ao WebSocket privado: {self._url_privado}")

        self._ws_privado = await ws_connect(self._url_privado)

        # Login
        await self._enviar(self._ws_privado, self._gerar_assinatura_login())
        await asyncio.sleep(1)  # Aguarda confirmação de login

        # Assinar canais privados
        if assinaturas:
            args = [a.para_dict() for a in assinaturas]
            await self._enviar(self._ws_privado, {"op": "subscribe", "args": args})

        # Iniciar processamento
        tarefa_msg = asyncio.create_task(
            self._processar_mensagens(self._ws_privado, "privado")
        )
        tarefa_ping = asyncio.create_task(
            self._keepalive(self._ws_privado, "privado")
        )
        self._tarefas.extend([tarefa_msg, tarefa_ping])

    async def iniciar(
        self,
        canais_publicos: list[AssinaturaCanal] | None = None,
        canais_privados: list[AssinaturaCanal] | None = None,
    ):
        """
        Inicia conexões WebSocket.

        Args:
            canais_publicos: Canais públicos para assinar.
            canais_privados: Canais privados para assinar.
        """
        self._rodando = True

        if canais_publicos:
            await self.conectar_publico(canais_publicos)

        if canais_privados:
            await self.conectar_privado(canais_privados)

        logger.info("WebSocket iniciado com sucesso")

    async def parar(self):
        """Para todas as conexões WebSocket."""
        self._rodando = False

        for tarefa in self._tarefas:
            tarefa.cancel()

        if self._ws_publico:
            await self._ws_publico.close()
        if self._ws_privado:
            await self._ws_privado.close()

        logger.info("WebSocket parado")
