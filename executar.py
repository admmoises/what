#!/usr/bin/env python3
"""
Ponto de entrada principal do Bot de Trading OKX.

Uso:
    python executar.py
    python executar.py --config config/config.json
    python executar.py --demo --debug
"""

from bot.main import executar

if __name__ == "__main__":
    executar()
