"""
Gerenciador de Ordens.

Responsável por rastrear, criar e gerenciar ordens de trading,
mantendo um registro local sincronizado com a exchange.
"""

import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Any

from bot.cliente_okx import ClienteOKX, LadoOrdem, TipoOrdem, ModoTrade
from bot.utils.logger import configurar_logger
from bot.utils.helpers import formatar_preco, formatar_quantidade

logger = configurar_logger("ordens")


class StatusOrdem(str, Enum):
    """Status possíveis de uma ordem."""
    PENDENTE = "pendente"
    ABERTA = "live"
    PARCIALMENTE_PREENCHIDA = "partially_filled"
    PREENCHIDA = "filled"
    CANCELADA = "canceled"
    ERRO = "erro"


@dataclass
class OrdemLocal:
    """Representação local de uma ordem."""
    id_cliente: str
    par: str
    lado: LadoOrdem
    tipo: TipoOrdem
    quantidade: str
    preco: str | None
    status: StatusOrdem = StatusOrdem.PENDENTE
    id_exchange: str = ""
    quantidade_preenchida: str = "0"
    preco_medio: str = "0"
    timestamp_criacao: float = field(default_factory=time.time)
    timestamp_atualizacao: float = field(default_factory=time.time)
    dados_extra: dict = field(default_factory=dict)


class GerenciadorOrdens:
    """
    Gerencia o ciclo de vida completo das ordens.

    Mantém rastreamento local de todas as ordens e fornece
    métodos para criação, cancelamento e consulta.
    """

    def __init__(self, cliente: ClienteOKX, modo_trade: ModoTrade = ModoTrade.SPOT):
        self._cliente = cliente
        self._modo_trade = modo_trade
        self._ordens: dict[str, OrdemLocal] = {}
        self._contador_ordens = 0

    def _gerar_id_cliente(self) -> str:
        """Gera ID único para ordem."""
        self._contador_ordens += 1
        return f"bot_{int(time.time())}_{self._contador_ordens}"

    @property
    def ordens_ativas(self) -> list[OrdemLocal]:
        """Retorna ordens que estão ativas (abertas ou parcialmente preenchidas)."""
        return [
            o for o in self._ordens.values()
            if o.status in (StatusOrdem.ABERTA, StatusOrdem.PARCIALMENTE_PREENCHIDA, StatusOrdem.PENDENTE)
        ]

    @property
    def ordens_compra_ativas(self) -> list[OrdemLocal]:
        """Retorna ordens de compra ativas."""
        return [o for o in self.ordens_ativas if o.lado == LadoOrdem.COMPRA]

    @property
    def ordens_venda_ativas(self) -> list[OrdemLocal]:
        """Retorna ordens de venda ativas."""
        return [o for o in self.ordens_ativas if o.lado == LadoOrdem.VENDA]

    def criar_ordem_limite(
        self,
        par: str,
        lado: LadoOrdem,
        preco: float,
        quantidade: float,
        casas_preco: int = 2,
        casas_quantidade: int = 6,
    ) -> OrdemLocal:
        """
        Cria uma ordem limite.

        Args:
            par: Par de trading.
            lado: COMPRA ou VENDA.
            preco: Preço limite.
            quantidade: Quantidade.
            casas_preco: Casas decimais do preço.
            casas_quantidade: Casas decimais da quantidade.

        Returns:
            Ordem local criada.
        """
        id_cliente = self._gerar_id_cliente()
        preco_fmt = formatar_preco(preco, casas_preco)
        qtd_fmt = formatar_quantidade(quantidade, casas_quantidade)

        ordem = OrdemLocal(
            id_cliente=id_cliente,
            par=par,
            lado=lado,
            tipo=TipoOrdem.LIMITE,
            quantidade=qtd_fmt,
            preco=preco_fmt,
        )

        try:
            resultado = self._cliente.criar_ordem(
                par=par,
                lado=lado,
                tipo=TipoOrdem.LIMITE,
                quantidade=qtd_fmt,
                preco=preco_fmt,
                modo_trade=self._modo_trade,
                id_cliente=id_cliente,
            )

            if resultado.get("sCode") == "0":
                ordem.id_exchange = resultado.get("ordId", "")
                ordem.status = StatusOrdem.ABERTA
                logger.info(
                    f"Ordem limite criada: {lado.value} {qtd_fmt} {par} @ {preco_fmt} "
                    f"[ID: {ordem.id_exchange}]"
                )
            else:
                ordem.status = StatusOrdem.ERRO
                ordem.dados_extra["erro"] = resultado.get("sMsg", "")
                logger.error(f"Erro ao criar ordem: {resultado.get('sMsg')}")

        except Exception as e:
            ordem.status = StatusOrdem.ERRO
            ordem.dados_extra["erro"] = str(e)
            logger.error(f"Exceção ao criar ordem: {e}")

        self._ordens[id_cliente] = ordem
        return ordem

    def criar_ordem_mercado(
        self,
        par: str,
        lado: LadoOrdem,
        quantidade: float,
        casas_quantidade: int = 6,
    ) -> OrdemLocal:
        """
        Cria uma ordem a mercado.

        Args:
            par: Par de trading.
            lado: COMPRA ou VENDA.
            quantidade: Quantidade.
            casas_quantidade: Casas decimais da quantidade.

        Returns:
            Ordem local criada.
        """
        id_cliente = self._gerar_id_cliente()
        qtd_fmt = formatar_quantidade(quantidade, casas_quantidade)

        ordem = OrdemLocal(
            id_cliente=id_cliente,
            par=par,
            lado=lado,
            tipo=TipoOrdem.MERCADO,
            quantidade=qtd_fmt,
            preco=None,
        )

        try:
            resultado = self._cliente.criar_ordem(
                par=par,
                lado=lado,
                tipo=TipoOrdem.MERCADO,
                quantidade=qtd_fmt,
                modo_trade=self._modo_trade,
                id_cliente=id_cliente,
            )

            if resultado.get("sCode") == "0":
                ordem.id_exchange = resultado.get("ordId", "")
                ordem.status = StatusOrdem.PREENCHIDA
                logger.info(
                    f"Ordem a mercado executada: {lado.value} {qtd_fmt} {par} "
                    f"[ID: {ordem.id_exchange}]"
                )
            else:
                ordem.status = StatusOrdem.ERRO
                ordem.dados_extra["erro"] = resultado.get("sMsg", "")

        except Exception as e:
            ordem.status = StatusOrdem.ERRO
            ordem.dados_extra["erro"] = str(e)
            logger.error(f"Exceção ao criar ordem mercado: {e}")

        self._ordens[id_cliente] = ordem
        return ordem

    def cancelar_ordem(self, id_cliente: str) -> bool:
        """
        Cancela uma ordem pelo ID do cliente.

        Args:
            id_cliente: ID da ordem local.

        Returns:
            True se cancelada com sucesso.
        """
        ordem = self._ordens.get(id_cliente)
        if not ordem:
            logger.warning(f"Ordem não encontrada: {id_cliente}")
            return False

        if ordem.status not in (StatusOrdem.ABERTA, StatusOrdem.PARCIALMENTE_PREENCHIDA):
            logger.warning(f"Ordem {id_cliente} não pode ser cancelada (status: {ordem.status})")
            return False

        try:
            resultado = self._cliente.cancelar_ordem(ordem.par, ordem.id_exchange)
            if resultado.get("sCode") == "0":
                ordem.status = StatusOrdem.CANCELADA
                ordem.timestamp_atualizacao = time.time()
                logger.info(f"Ordem cancelada: {id_cliente}")
                return True
            else:
                logger.error(f"Falha ao cancelar ordem: {resultado.get('sMsg')}")
                return False

        except Exception as e:
            logger.error(f"Exceção ao cancelar ordem: {e}")
            return False

    def cancelar_todas(self, par: str | None = None) -> int:
        """
        Cancela todas as ordens ativas.

        Args:
            par: Se especificado, cancela apenas ordens deste par.

        Returns:
            Número de ordens canceladas.
        """
        canceladas = 0
        for ordem in self.ordens_ativas:
            if par and ordem.par != par:
                continue
            if self.cancelar_ordem(ordem.id_cliente):
                canceladas += 1

        logger.info(f"Total de ordens canceladas: {canceladas}")
        return canceladas

    def atualizar_ordem(self, dados_exchange: dict):
        """
        Atualiza ordem local com dados da exchange (via WebSocket).

        Args:
            dados_exchange: Dados da ordem recebidos da exchange.
        """
        id_cliente = dados_exchange.get("clOrdId", "")
        id_exchange = dados_exchange.get("ordId", "")

        # Buscar por ID cliente ou ID exchange
        ordem = self._ordens.get(id_cliente)
        if not ordem:
            for o in self._ordens.values():
                if o.id_exchange == id_exchange:
                    ordem = o
                    break

        if not ordem:
            return

        status_map = {
            "live": StatusOrdem.ABERTA,
            "partially_filled": StatusOrdem.PARCIALMENTE_PREENCHIDA,
            "filled": StatusOrdem.PREENCHIDA,
            "canceled": StatusOrdem.CANCELADA,
        }

        novo_status = status_map.get(dados_exchange.get("state", ""))
        if novo_status:
            ordem.status = novo_status

        ordem.quantidade_preenchida = dados_exchange.get("accFillSz", ordem.quantidade_preenchida)
        ordem.preco_medio = dados_exchange.get("avgPx", ordem.preco_medio)
        ordem.timestamp_atualizacao = time.time()

        logger.debug(
            f"Ordem atualizada: {ordem.id_cliente} -> {ordem.status.value} "
            f"(preenchido: {ordem.quantidade_preenchida})"
        )

    def obter_resumo(self) -> dict:
        """Retorna resumo das ordens gerenciadas."""
        total = len(self._ordens)
        ativas = len(self.ordens_ativas)
        preenchidas = sum(1 for o in self._ordens.values() if o.status == StatusOrdem.PREENCHIDA)
        canceladas = sum(1 for o in self._ordens.values() if o.status == StatusOrdem.CANCELADA)
        erros = sum(1 for o in self._ordens.values() if o.status == StatusOrdem.ERRO)

        return {
            "total": total,
            "ativas": ativas,
            "preenchidas": preenchidas,
            "canceladas": canceladas,
            "erros": erros,
        }
