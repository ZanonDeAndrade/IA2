"""Chance de vitória e classificação de lances (limites em classificacao.toml).

Usa as mesmas classes e limites de ``agent/classifier.py`` (documentação, seção 8):
``erro_grave`` (queda >= 30), ``erro`` (>= 20), ``imprecisao`` (>= 10) e ``aceitavel``.
A ferramenta ``analisar_partida`` precisa classificar os lances dentro do
servidor MCP, por isso a regra também vive aqui.
"""

from __future__ import annotations

import math
import tomllib
from functools import lru_cache
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "classificacao.toml"

CLASSES = ("aceitavel", "imprecisao", "erro", "erro_grave")


@lru_cache(maxsize=1)
def config() -> dict:
    with open(CONFIG, "rb") as f:
        return tomllib.load(f)


def chance_de_vitoria(cp: float) -> float:
    """Centipeões (ponto de vista do jogador) -> chance de vitória de 0 a 100."""
    k = config()["k"]
    return 50 + 50 * (2 / (1 + math.exp(-k * cp)) - 1)


def chance_da_avaliacao(cp: int | None, mate: int | None) -> float:
    """Avaliação de um ponto de vista (cp ou mate) -> chance de vitória desse lado.
    Mate forçado conta como 100% (a favor) ou 0% (contra)."""
    if mate is not None:
        return 100.0 if mate > 0 else 0.0
    return round(chance_de_vitoria(cp or 0), 2)


def classificar(queda: float) -> str:
    """Queda na chance de vitória -> 'erro_grave' | 'erro' | 'imprecisao' | 'aceitavel'."""
    lim = config()["limites"]
    if queda >= lim["erro_grave"]:
        return "erro_grave"
    if queda >= lim["erro"]:
        return "erro"
    if queda >= lim["imprecisao"]:
        return "imprecisao"
    return "aceitavel"


def precisao_do_lance(queda: float) -> float:
    """Precisão de um lance (0-100) pela fórmula usada pela Lichess."""
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * queda) - 3.1669))


def precisao(quedas: list[float]) -> float | None:
    """Precisão média de uma lista de quedas, ou None se a lista for vazia."""
    if not quedas:
        return None
    return round(sum(precisao_do_lance(q) for q in quedas) / len(quedas), 1)
