from types import SimpleNamespace
import os

import chess
import pytest

from mcp_server.tools import engine
from mcp_server.tools.jogo import PERFIS, jogar_stockfish, opcoes_de_forca


def test_descoberta_das_opcoes_uci_e_limites():
    skill = SimpleNamespace(type="spin", min=0, max=10)
    elo = SimpleNamespace(type="spin", min=1500, max=1900)
    limitar = SimpleNamespace(type="check")
    opcoes = {"Skill Level": skill, "UCI_Elo": elo, "UCI_LimitStrength": limitar}
    assert opcoes_de_forca(opcoes, "iniciante") == {"Skill Level": 0, "UCI_LimitStrength": False}
    assert opcoes_de_forca(opcoes, "avancado") == {"UCI_Elo": 1900, "UCI_LimitStrength": True}
    assert opcoes_de_forca({"Skill Level": skill}, "avancado") == {"Skill Level": 10}
    assert opcoes_de_forca({"UCI_Elo": elo, "UCI_LimitStrength": limitar}, "iniciante") == {
        "UCI_Elo": 1500, "UCI_LimitStrength": True,
    }
    assert opcoes_de_forca({}, "mestre") == {}


@pytest.mark.skipif(not os.getenv("STOCKFISH_PATH"), reason="requer o Stockfish real")
def test_quatro_perfis_reais_e_avaliacao_sem_limitacao():
    fen = chess.STARTING_FEN
    movimentos = ["e2e4"]
    tabuleiro = chess.Board(fen)
    tabuleiro.push_uci(movimentos[0])
    try:
        avaliacao = engine.analisar_posicao(tabuleiro.fen(), 6, 1)
        _, motor = engine._motor_ativo
        for nivel in PERFIS:
            resposta = jogar_stockfish(fen, movimentos, nivel)
            assert "stockfish" in resposta["motor"].lower()
            assert tabuleiro.parse_uci(resposta["uci"]) in tabuleiro.legal_moves
            assert resposta["opcoes_uci"] == opcoes_de_forca(motor.options, nivel)
            assert engine.analisar_posicao(tabuleiro.fen(), 6, 1) == avaliacao
            for nome in ("Skill Level", "UCI_LimitStrength", "UCI_Elo"):
                if nome in motor.options:
                    assert motor.protocol.config[nome] == motor.options[nome].default
    finally:
        engine._encerrar_motor(aguardar=True)


def test_historico_invalido_rejeitado_antes_do_motor():
    with pytest.raises(ValueError):
        jogar_stockfish(chess.STARTING_FEN, ["0000"], "iniciante")
