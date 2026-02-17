# Bot de Trading OKX

Bot automatizado de trading para a exchange [OKX](https://www.okx.com), inspirado na arquitetura do [Hummingbot](https://github.com/hummingbot/hummingbot).

## Funcionalidades

- **Cliente REST completo** para a API v5 da OKX com autenticação HMAC-SHA256
- **Cliente WebSocket** para dados de mercado e conta em tempo real
- **Estratégia Market Making** com múltiplos níveis, ajuste de inventário e rebalanceamento automático
- **Estratégia Grid Trading** com grade linear ou geométrica e recriação automática de ordens
- **Gerenciamento de risco** com stop-loss, controle de drawdown e kill switch
- **Gerenciamento de ordens** com rastreamento local e sincronização com a exchange
- **Modo demo** para testes sem risco com dinheiro real

## Estrutura do Projeto

```
├── executar.py                  # Ponto de entrada principal
├── requirements.txt             # Dependências
├── config/
│   └── config_exemplo.json      # Configuração de exemplo
├── bot/
│   ├── main.py                  # Orquestrador do bot
│   ├── cliente_okx.py           # Cliente REST da API OKX
│   ├── websocket_okx.py         # Cliente WebSocket
│   ├── gerenciador_ordens.py    # Gerenciamento de ordens
│   ├── gerenciador_risco.py     # Gerenciamento de risco
│   ├── estrategias/
│   │   ├── base.py              # Classe base de estratégias
│   │   ├── market_making.py     # Estratégia Market Making
│   │   └── grid_trading.py      # Estratégia Grid Trading
│   └── utils/
│       ├── logger.py            # Sistema de logging
│       └── helpers.py           # Funções auxiliares
└── testes/
    ├── teste_cliente_okx.py     # Testes do cliente e componentes
    └── teste_estrategias.py     # Testes das estratégias
```

## Instalação

```bash
# Clonar repositório
git clone <url-do-repo>
cd okx-trading-bot

# Instalar dependências
pip install -r requirements.txt

# Configurar credenciais
cp config/config_exemplo.json config/config.json
# Editar config/config.json com suas credenciais da OKX
```

## Configuração

### Credenciais da API OKX

1. Acesse [OKX API Management](https://www.okx.com/account/my-api)
2. Crie uma nova API Key com permissões de Trading
3. Copie a API Key, Secret Key e Passphrase
4. Configure no arquivo `config/config.json`

**Importante:** Comece sempre com `"demo": true` para testar com dinheiro virtual.

### Parâmetros de Configuração

```json
{
  "okx": {
    "api_key": "SUA_API_KEY",
    "secret_key": "SUA_SECRET_KEY",
    "passphrase": "SUA_PASSPHRASE",
    "demo": true
  },
  "estrategia": {
    "tipo": "market_making",
    "par": "BTC-USDT",
    "intervalo_ciclo": 1.0
  }
}
```

### Estratégia Market Making

Coloca ordens de compra e venda ao redor do preço de mercado:

| Parâmetro | Descrição | Padrão |
|-----------|-----------|--------|
| `spread_bid` | Spread da compra (%) | 0.1% |
| `spread_ask` | Spread da venda (%) | 0.1% |
| `tamanho_ordem` | Quantidade por ordem | 0.001 |
| `num_niveis` | Níveis de cada lado | 3 |
| `ajuste_inventario` | Ajustar por posição | true |

### Estratégia Grid Trading

Cria grade de ordens em faixa de preço definida:

| Parâmetro | Descrição | Padrão |
|-----------|-----------|--------|
| `preco_minimo` | Limite inferior | - |
| `preco_maximo` | Limite superior | - |
| `num_grades` | Número de níveis | 10 |
| `grade_geometrica` | Espaçamento percentual | false |

### Gerenciamento de Risco

| Parâmetro | Descrição | Padrão |
|-----------|-----------|--------|
| `stop_loss_percentual` | Stop-loss por trade | 2% |
| `stop_loss_diario` | Perda máxima diária | 5% |
| `drawdown_maximo` | Drawdown máximo | 10% |
| `kill_switch_perda` | Perda que para tudo | 15% |
| `max_ordens_abertas` | Máximo de ordens | 20 |

## Uso

```bash
# Executar com configuração padrão
python executar.py

# Especificar arquivo de configuração
python executar.py --config config/config.json

# Modo debug (logs detalhados)
python executar.py --debug

# Executar como módulo
python -m bot.main --config config/config.json
```

## Testes

```bash
# Executar todos os testes
python -m pytest testes/ -v

# Executar testes específicos
python -m pytest testes/teste_cliente_okx.py -v
python -m pytest testes/teste_estrategias.py -v

# Com unittest
python -m unittest discover testes/
```

## Aviso Legal

**Este software é fornecido apenas para fins educacionais e de pesquisa.**

- Trading de criptomoedas envolve riscos significativos
- Você pode perder todo o capital investido
- Sempre comece com o modo demo (`"demo": true`)
- Não invista dinheiro que não pode perder
- O autor não se responsabiliza por perdas financeiras
