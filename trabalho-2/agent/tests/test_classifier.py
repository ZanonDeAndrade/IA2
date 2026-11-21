import chess
import pytest
from chess.engine import Cp, Mate, MateGiven, PovScore

from agent.classifier import chance_de_vitoria, classificar_lance, classificar_queda


@pytest.mark.parametrize(("delta", "classe"), [
    (-25, "aceitavel"), (9.999, "aceitavel"), (10, "imprecisao"),
    (19.999, "imprecisao"), (20, "erro"), (29.999, "erro"), (30, "erro_grave"),
])
def test_fronteiras(delta, classe):
    assert classificar_queda(delta) == classe


def test_curva_extremos_e_configuracao():
    assert chance_de_vitoria(0) == 50
    assert chance_de_vitoria(100) == pytest.approx(59.1026, abs=0.001)
    assert chance_de_vitoria(-100) + chance_de_vitoria(100) == pytest.approx(100)
    assert chance_de_vitoria(10**500) == 100
    assert chance_de_vitoria(-10**500) == 0
    assert classificar_queda(12, {"imprecisao": 5, "erro": 10, "erro_grave": 15}) == "erro"
    with pytest.raises(ValueError):
        chance_de_vitoria(None)


@pytest.mark.parametrize("cor", [chess.WHITE, chess.BLACK])
def test_perspectiva_e_mate(cor):
    antes = PovScore(Cp(400), cor)
    depois = PovScore(Cp(400), not cor)
    assert classificar_lance(antes, depois, jogador=cor) == "erro_grave"
    assert classificar_lance(antes, PovScore(Mate(0), not cor), jogador=cor) == "aceitavel"
    assert classificar_lance(PovScore(MateGiven, cor), PovScore(Mate(-1), cor), jogador=cor) == "erro_grave"
    assert chance_de_vitoria(None, 3) == 100
    assert chance_de_vitoria(None, -3) == 0
    with pytest.raises(ValueError):
        classificar_lance(antes, depois)
