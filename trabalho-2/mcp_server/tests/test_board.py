import json

import chess
import pytest

from mcp_server.tools.board import descrever_posicao


MATE_EM_UM = "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1"
XEQUE_MATE = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
AFOGAMENTO = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"


@pytest.mark.parametrize("fen", ["inválido", "8/8/8/8/8/8/8/8 w - - 0 1"])
def test_descrever_rejeita_fen_invalido(fen):
    with pytest.raises(ValueError, match="FEN"):
        descrever_posicao(fen)


def test_posicao_inicial():
    fatos = descrever_posicao(chess.STARTING_FEN)
    assert json.loads(json.dumps(fatos)) == fatos
    assert fatos["lado_a_jogar"] == "white"
    material = {"peao": 8, "cavalo": 2, "bispo": 2, "torre": 2, "dama": 1, "rei": 1}
    assert fatos["material"] == {"white": material, "black": material}
    assert len(fatos["pecas"]) == 32
    assert {"cor": "black", "tipo": "dama", "casa": "d8"} in fatos["pecas"]
    assert fatos["pecas_atacadas"] == fatos["pecas_cravadas"] == fatos["xeques_possiveis"] == []
    assert fatos["reis"]["white"] == {
        "casa": "e1", "em_xeque": False, "atacantes": [],
        "casas_adjacentes_atacadas": [], "peoes_adjacentes": ["d2", "e2", "f2"],
    }


def test_ataques_defesas_e_cravada_absoluta():
    fen = "4r1k1/8/8/8/2n5/8/4B3/4K3 w - - 0 1"
    fatos = descrever_posicao(fen)
    atacadas = {peca["casa"]: peca for peca in fatos["pecas_atacadas"]}
    assert atacadas["e2"]["atacantes"] == ["e8"] and atacadas["e2"]["defensores"] == ["e1"]
    assert atacadas["c4"]["atacantes"] == ["e2"] and atacadas["c4"]["defensores"] == []
    assert "e2c4" not in {lance.uci() for lance in chess.Board(fen).legal_moves}
    assert any(peca["casa"] == "c4" for peca in fatos["pecas_indefesas"])
    assert all(peca["tipo"] != "rei" for peca in fatos["pecas_indefesas"])
    assert fatos["pecas_cravadas"] == [
        {"cor": "white", "tipo": "bispo", "casa": "e2", "rei": "e1", "atacantes": ["e8"]},
    ]


def test_xeque_e_casas_do_rei():
    fatos = descrever_posicao("4k3/8/8/8/8/8/4r3/4K3 w - - 0 1")
    assert fatos["em_xeque"] and not fatos["xeque_mate"] and not fatos["afogamento"]
    rei = fatos["reis"]["white"]
    assert rei["em_xeque"] and rei["atacantes"] == ["e2"]
    assert rei["casas_adjacentes_atacadas"] == ["d2", "f2"]
    assert fatos["xeques_possiveis"] == []


def test_xeques_legais_e_mate_em_san_e_uci():
    fatos = descrever_posicao(MATE_EM_UM)
    assert {"san": "Qg7#", "uci": "f7g7"} in fatos["xeques_possiveis"]
    tabuleiro = chess.Board(MATE_EM_UM)
    for lance in fatos["xeques_possiveis"]:
        movimento = tabuleiro.parse_uci(lance["uci"])
        assert tabuleiro.san(movimento) == lance["san"] and tabuleiro.gives_check(movimento)


@pytest.mark.parametrize(("fen", "mate"), [(XEQUE_MATE, True), (AFOGAMENTO, False)])
def test_posicoes_terminais(fen, mate):
    fatos = descrever_posicao(fen)
    assert fatos["lado_a_jogar"] == "black"
    assert fatos["xeque_mate"] is mate and fatos["em_xeque"] is mate
    assert fatos["afogamento"] is (not mate)
    assert fatos["xeques_possiveis"] == []
