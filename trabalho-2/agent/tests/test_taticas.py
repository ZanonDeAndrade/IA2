import chess
import pytest

from agent.taticas import candidatos_taticos, justificar_alternativa


@pytest.mark.parametrize(("fen", "erro", "linha", "tema"), [
    ("r7/2q2kp1/3p1pn1/3PpNp1/8/p1P4P/Pr3PPK/1R1QR3 b - - 1 30", "Rxf2", ["Rb7", "Qxb7", "Nxd6+", "Kg8", "Nxb7"], "cravada"),
    ("2kr2r1/2p5/p2qR1N1/np1p2pP/8/7Q/PPP2PP1/6K1 b - - 0 28", "Qb4", ["Re4+", "Kb7", "Rxb4"], "ataque_descoberto"),
    ("r1q3k1/4bppp/pp2pn2/4B3/8/2N2Q2/PPPR1PPP/6K1 b - - 0 18", "Nd7", ["Rxd7", "Qxd7", "Qxa8+"], "desvio"),
    ("r2q1rk1/pp1n1ppb/2p1p1P1/3pB3/1bPP4/2N2P2/PP1QP3/R3KB1R b KQ - 0 14", "Bxg6", ["Rh8+", "Kxh8", "Qh6+", "Kg8", "Qxg7#"], "atracao"),
    ("r1k4r/8/8/8/3K4/8/8/R7 w - - 0 1", "Kd5", ["Rh5+", "Kc7"], None),
])
def test_motivo_requer_evidencia_em_variante_legal(fen, erro, linha, tema):
    posicao = chess.Board(fen)
    posicao.push_san(erro)
    original = posicao.fen()
    candidatos = candidatos_taticos(posicao, {"linha_principal": linha})
    assert (candidatos[0].tema if candidatos else None) == tema
    assert posicao.fen() == original


def test_espeto_pede_que_o_alvo_dianteiro_saia_antes_da_captura():
    posicao = chess.Board("q7/8/8/k7/8/8/8/1R4K1 w - - 0 1")
    assert candidatos_taticos(posicao, {"linha_principal": ["Ra1+", "Kb5"]}) == []
    evidencias = candidatos_taticos(posicao, {"linha_principal": ["Ra1+", "Kb5", "Rxa8"]})
    assert [e.tema for e in evidencias] == ["espeto"]


def test_justificativa_so_usa_a_variante_da_alternativa():
    inicio = chess.Board()
    assert not justificar_alternativa(inicio, "d4", ["e4", "e5"])
    assert "resposta imediata" in justificar_alternativa(inicio, "d4", ["d4", "d5"])
    en_passant = chess.Board("7k/8/8/8/3p4/8/4P3/7K w - - 0 1")
    assert not justificar_alternativa(en_passant, "e4", ["e4", "dxe3"])
