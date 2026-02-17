"""
Estratégia de Grid Trading.

Cria uma grade de ordens de compra e venda em intervalos fixos
de preço, lucrando com a oscilação do mercado dentro da faixa.
"""

from dataclasses import dataclass, field

from bot.cliente_okx import ClienteOKX, LadoOrdem
from bot.gerenciador_ordens import GerenciadorOrdens, StatusOrdem, OrdemLocal
from bot.gerenciador_risco import GerenciadorRisco
from bot.estrategias.base import EstrategiaBase, TickerAtual
from bot.utils.logger import configurar_logger
from bot.utils.helpers import formatar_preco

logger = configurar_logger("estrategia.grid")


@dataclass
class ConfigGrid:
    """Configuração da estratégia de Grid Trading."""
    # Faixa de preço
    preco_minimo: float = 0.0  # Limite inferior da grade
    preco_maximo: float = 0.0  # Limite superior da grade

    # Estrutura da grade
    num_grades: int = 10  # Número de níveis na grade
    tamanho_ordem: float = 0.001  # Quantidade por ordem

    # Tipo de grade
    grade_geometrica: bool = False  # True = espaçamento percentual, False = espaçamento fixo

    # Controle
    casas_preco: int = 2
    casas_quantidade: int = 6
    recriar_ordens_preenchidas: bool = True  # Recriar ordens do lado oposto quando preenchida

    # Lucro
    lucro_por_grade: float = 0.0  # Calculado automaticamente


@dataclass
class NivelGrade:
    """Representação de um nível na grade."""
    indice: int
    preco: float
    ordem_compra: OrdemLocal | None = None
    ordem_venda: OrdemLocal | None = None
    preenchido: bool = False


class EstrategiaGridTrading(EstrategiaBase):
    """
    Estratégia de Grid Trading.

    Divide uma faixa de preço em N níveis e coloca ordens de compra
    abaixo do preço atual e ordens de venda acima. Quando uma ordem
    é preenchida, cria uma ordem oposta no nível correspondente.

    Exemplo com grade de 5 níveis (preço atual = 100):
    - Nível 5: Venda @ 110
    - Nível 4: Venda @ 105
    - Nível 3: --- (preço atual) ---
    - Nível 2: Compra @ 95
    - Nível 1: Compra @ 90

    Quando Compra @ 95 é preenchida → cria Venda @ 100
    Quando Venda @ 105 é preenchida → cria Compra @ 100
    """

    def __init__(
        self,
        cliente: ClienteOKX,
        gerenciador_ordens: GerenciadorOrdens,
        gerenciador_risco: GerenciadorRisco,
        par: str,
        config: ConfigGrid | None = None,
        intervalo_ciclo: float = 2.0,
    ):
        super().__init__(cliente, gerenciador_ordens, gerenciador_risco, par, intervalo_ciclo)
        self._config = config or ConfigGrid()
        self._niveis: list[NivelGrade] = []
        self._grade_inicializada = False
        self._lucro_total_grade = 0.0

    def ao_iniciar(self):
        """Inicializa a grade."""
        if self._config.preco_minimo <= 0 or self._config.preco_maximo <= 0:
            logger.error("Preço mínimo e máximo devem ser definidos")
            self.parar()
            return

        if self._config.preco_minimo >= self._config.preco_maximo:
            logger.error("Preço mínimo deve ser menor que preço máximo")
            self.parar()
            return

        self._calcular_niveis()
        logger.info(
            f"Grid Trading iniciado para {self._par} | "
            f"Faixa: {self._config.preco_minimo} - {self._config.preco_maximo} | "
            f"Grades: {self._config.num_grades} | "
            f"Tamanho: {self._config.tamanho_ordem}"
        )

    def ao_parar(self):
        """Limpeza ao parar."""
        logger.info(
            f"Grid Trading parado | Lucro total da grade: {self._lucro_total_grade:.4f}"
        )

    def ao_atualizar_ordem(self, dados_ordem: dict):
        """Processa atualizações de ordens e recria ordens opostas."""
        self._ordens.atualizar_ordem(dados_ordem)

        estado = dados_ordem.get("state", "")
        if estado != "filled":
            return

        if not self._config.recriar_ordens_preenchidas:
            return

        id_cliente = dados_ordem.get("clOrdId", "")
        lado = dados_ordem.get("side", "")
        preco_preenchido = float(dados_ordem.get("avgPx", 0))

        # Encontrar nível correspondente
        nivel = self._encontrar_nivel_por_ordem(id_cliente)
        if not nivel:
            return

        # Calcular lucro
        intervalo = self._calcular_intervalo()

        if lado == "buy":
            # Compra preenchida → criar venda um nível acima
            preco_venda = preco_preenchido + intervalo
            if preco_venda <= self._config.preco_maximo:
                self._criar_ordem_grade(nivel.indice, LadoOrdem.VENDA, preco_venda)
                self._lucro_total_grade += intervalo * self._config.tamanho_ordem
                logger.info(
                    f"Grade: Compra preenchida @ {preco_preenchido:.{self._config.casas_preco}f} "
                    f"→ Criando venda @ {preco_venda:.{self._config.casas_preco}f}"
                )

        elif lado == "sell":
            # Venda preenchida → criar compra um nível abaixo
            preco_compra = preco_preenchido - intervalo
            if preco_compra >= self._config.preco_minimo:
                self._criar_ordem_grade(nivel.indice, LadoOrdem.COMPRA, preco_compra)
                self._lucro_total_grade += intervalo * self._config.tamanho_ordem
                logger.info(
                    f"Grade: Venda preenchida @ {preco_preenchido:.{self._config.casas_preco}f} "
                    f"→ Criando compra @ {preco_compra:.{self._config.casas_preco}f}"
                )

    def _calcular_intervalo(self) -> float:
        """Calcula o intervalo entre níveis da grade."""
        if self._config.grade_geometrica:
            # Espaçamento percentual
            ratio = (self._config.preco_maximo / self._config.preco_minimo) ** (
                1 / self._config.num_grades
            )
            return ratio - 1  # Retorna o fator multiplicador
        else:
            # Espaçamento fixo
            return (
                self._config.preco_maximo - self._config.preco_minimo
            ) / self._config.num_grades

    def _calcular_niveis(self):
        """Calcula os preços de cada nível da grade."""
        self._niveis.clear()
        intervalo = self._calcular_intervalo()

        for i in range(self._config.num_grades + 1):
            if self._config.grade_geometrica:
                preco = self._config.preco_minimo * (
                    (1 + intervalo) ** i
                )
            else:
                preco = self._config.preco_minimo + (intervalo * i)

            nivel = NivelGrade(indice=i, preco=preco)
            self._niveis.append(nivel)

        self._config.lucro_por_grade = intervalo * self._config.tamanho_ordem

        logger.info(f"Grade calculada com {len(self._niveis)} níveis:")
        for n in self._niveis:
            logger.debug(f"  Nível {n.indice}: {n.preco:.{self._config.casas_preco}f}")

    def _encontrar_nivel_por_ordem(self, id_cliente: str) -> NivelGrade | None:
        """Encontra o nível da grade associado a uma ordem."""
        for nivel in self._niveis:
            if nivel.ordem_compra and nivel.ordem_compra.id_cliente == id_cliente:
                return nivel
            if nivel.ordem_venda and nivel.ordem_venda.id_cliente == id_cliente:
                return nivel
        return None

    def _criar_ordem_grade(self, indice_nivel: int, lado: LadoOrdem, preco: float):
        """Cria uma ordem para um nível específico da grade."""
        permitido, motivo = self._risco.pode_criar_ordem(
            self._config.tamanho_ordem * preco,
            len(self._ordens.ordens_ativas),
        )

        if not permitido:
            logger.warning(f"Ordem grade nível {indice_nivel} bloqueada: {motivo}")
            return

        ordem = self._ordens.criar_ordem_limite(
            par=self._par,
            lado=lado,
            preco=preco,
            quantidade=self._config.tamanho_ordem,
            casas_preco=self._config.casas_preco,
            casas_quantidade=self._config.casas_quantidade,
        )

        # Associar ordem ao nível
        if indice_nivel < len(self._niveis):
            if lado == LadoOrdem.COMPRA:
                self._niveis[indice_nivel].ordem_compra = ordem
            else:
                self._niveis[indice_nivel].ordem_venda = ordem

    def _inicializar_grade(self, preco_atual: float):
        """
        Inicializa a grade com ordens baseadas no preço atual.

        Compras abaixo do preço atual, vendas acima.
        """
        logger.info(f"Inicializando grade ao redor do preço {preco_atual}")

        for nivel in self._niveis:
            if nivel.preco < preco_atual:
                # Abaixo do preço → ordem de compra
                self._criar_ordem_grade(nivel.indice, LadoOrdem.COMPRA, nivel.preco)
            elif nivel.preco > preco_atual:
                # Acima do preço → ordem de venda
                self._criar_ordem_grade(nivel.indice, LadoOrdem.VENDA, nivel.preco)

        self._grade_inicializada = True
        logger.info(
            f"Grade inicializada com {len(self._ordens.ordens_ativas)} ordens ativas"
        )

    def executar_ciclo(self, ticker: TickerAtual):
        """
        Executa um ciclo de grid trading.

        No primeiro ciclo, inicializa a grade. Nos ciclos seguintes,
        monitora e mantém as ordens.
        """
        if self._risco.kill_switch_ativo:
            logger.warning("Kill switch ativo - ciclo ignorado")
            return

        preco_atual = ticker.ultimo_preco
        if preco_atual <= 0:
            return

        # Verificar se preço está dentro da faixa
        if preco_atual < self._config.preco_minimo or preco_atual > self._config.preco_maximo:
            logger.warning(
                f"Preço {preco_atual} fora da faixa da grade "
                f"({self._config.preco_minimo} - {self._config.preco_maximo})"
            )

        # Inicializar grade no primeiro ciclo
        if not self._grade_inicializada:
            self._inicializar_grade(preco_atual)

    def obter_status_grade(self) -> dict:
        """Retorna status detalhado da grade."""
        return {
            "par": self._par,
            "preco_minimo": self._config.preco_minimo,
            "preco_maximo": self._config.preco_maximo,
            "num_grades": self._config.num_grades,
            "intervalo": self._calcular_intervalo(),
            "lucro_por_grade": self._config.lucro_por_grade,
            "lucro_total": self._lucro_total_grade,
            "niveis": len(self._niveis),
            "ordens_ativas": len(self._ordens.ordens_ativas),
            "grade_inicializada": self._grade_inicializada,
        }
