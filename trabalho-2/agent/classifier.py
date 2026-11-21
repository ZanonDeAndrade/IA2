"""Classifica lances pela perda de chance de vitória, em pontos percentuais."""

from collections.abc import Mapping
from math import exp, isfinite
from typing import Literal

from chess.engine import PovScore

Classe = Literal["aceitavel", "imprecisao", "erro", "erro_grave"]
COEFICIENTE_LOGISTICO = 0.00368208
LIMITES = {"erro_grave": 30.0, "erro": 20.0, "imprecisao": 10.0}
CLASSES = ("aceitavel", "imprecisao", "erro", "erro_grave")


def chance_de_vitoria(cp: int | None, mate: int | None = None) -> float:
    """Recebe uma avaliação já normalizada. Mate zero indica que o jogador perdeu."""
    if (cp is None) == (mate is None):
        raise ValueError("Informe exatamente uma avaliação em cp ou mate.")
    if mate is not None:
        return 100.0 if mate > 0 else 0.0
    assert cp is not None
    # A partir daqui a curva já arredonda para um dos extremos em float.
    x = COEFICIENTE_LOGISTICO * max(-250_000, min(250_000, cp))
    if x >= 0:
        return 100.0 / (1.0 + exp(-x))
    e = exp(x)
    return 100.0 * e / (1.0 + e)


def _chance(avaliacao: int | PovScore, jogador: bool | None) -> float:
    if isinstance(avaliacao, int):
        return chance_de_vitoria(avaliacao)
    if jogador is None:
        raise ValueError("Informe a cor do jogador para normalizar o PovScore.")
    score = avaliacao.pov(jogador)
    if score.is_mate():
        # MateGiven e Mate(0) têm mate() == 0, mas sinal oposto.
        valor = score.mate() or score.score(mate_score=1)
        assert valor is not None
        return 100.0 if valor > 0 else 0.0
    return chance_de_vitoria(score.score())


def classificar_queda(delta: float, limites: Mapping[str, float] = LIMITES) -> Classe:
    """Aplica os limites à queda sem arredondar antes de classificar."""
    imprecisao, erro, grave = (limites[chave] for chave in CLASSES[1:])
    if not 0 <= imprecisao < erro < grave <= 100 or not isfinite(delta):
        raise ValueError("Queda ou limites inválidos.")
    if delta >= grave:
        return "erro_grave"
    if delta >= erro:
        return "erro"
    if delta >= imprecisao:
        return "imprecisao"
    return "aceitavel"


def classificar_lance(
    cp_antes: int | PovScore,
    cp_depois: int | PovScore,
    *,
    jogador: bool | None = None,
    limites: Mapping[str, float] = LIMITES,
) -> Classe:
    """Inteiros já estão na perspectiva do jogador; PovScore requer sua cor."""
    delta = _chance(cp_antes, jogador) - _chance(cp_depois, jogador)
    return classificar_queda(delta, limites)
