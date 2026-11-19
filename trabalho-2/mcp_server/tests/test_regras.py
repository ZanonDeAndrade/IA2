"""Testes de classificacao.py, notacao.py, temas.py e board.py (sem Stockfish)."""

import chess
import pytest

from mcp_server.tools import board as tb
from mcp_server.tools.classificacao import chance_da_avaliacao, chance_de_vitoria, classificar, precisao
from mcp_server.tools.notacao import interpretar_lance, limpar, san_en, san_pt
from mcp_server.tools.temas import TEMAS_DO_AGENTE, para_lichess, rotulo, tema_do_agente, traduzir

INICIAL = chess.STARTING_FEN


# -- classificação ------------------------------------------------------------

def test_chance_de_vitoria_simetrica():
    assert chance_de_vitoria(0) == pytest.approx(50)
    assert chance_de_vitoria(300) + chance_de_vitoria(-300) == pytest.approx(100)
    assert chance_de_vitoria(1000) > 95


def test_chance_com_mate_e_precisao():
    assert chance_da_avaliacao(None, 3) == 100.0
    assert chance_da_avaliacao(None, -1) == 0.0
    assert chance_da_avaliacao(10_000, None) == 100.0
    assert precisao([]) is None
    assert precisao([0, 0]) == 100.0
    assert precisao([50]) < 15


@pytest.mark.parametrize("queda, classe", [
    (0, "aceitavel"), (9.99, "aceitavel"), (10, "imprecisao"), (19.9, "imprecisao"),
    (20, "erro"), (29.9, "erro"), (30, "erro_grave"), (100, "erro_grave"),
])
def test_classificar_limites(queda, classe):
    assert classificar(queda) == classe


# -- notação ------------------------------------------------------------------

def test_san_pt_e_en():
    assert san_pt("Nf3") == "Cf3"
    assert san_pt("Qxd7+") == "Dxd7+"
    assert san_pt("Rae1") == "Tae1"
    assert san_pt("Kg1") == "Rg1"
    assert san_pt("e8=Q#") == "e8=D#"
    assert san_pt("O-O") == "O-O"
    assert san_en("Cf3") == "Nf3"
    assert san_en("Txe1") == "Rxe1"


def test_limpar_remove_numero_e_anotacao():
    assert limpar("12. Nf3!?") == "Nf3"
    assert limpar("12... Qxe4+") == "Qxe4"
    assert limpar("0-0-0") == "O-O-O"


def test_interpretar_ambiguidade_r_rei_torre():
    # Torre em a1 e rei em e1: "Rd1" é torre (inglês) e também rei (português).
    board = chess.Board("4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
    mv, notacao, ambiguo = interpretar_lance(board, "Rd1")
    assert (mv.uci(), notacao, ambiguo) == ("a1d1", "san", True)
    mv, notacao, ambiguo = interpretar_lance(board, "Rd1", preferir="pt")
    assert (mv.uci(), notacao, ambiguo) == ("e1d1", "san_pt", True)


# -- temas --------------------------------------------------------------------

def test_temas():
    assert traduzir("fork") == "garfo"
    assert traduzir("temaDesconhecido") == "temaDesconhecido"
    assert para_lichess("garfo") == "fork"
    assert para_lichess("pin") == "pin"
    assert para_lichess("peca_pendurada") == "hangingPiece"
    assert tema_do_agente("fork hangingPiece middlegame") == "garfo"
    assert tema_do_agente("hangingPiece") == "peca_pendurada"
    assert tema_do_agente(["backRankMate", "mateIn2"]) == "mate"
    assert tema_do_agente("endgame advantage") == "outro"
    assert rotulo("peca_pendurada") == "Peça pendurada"
    assert rotulo("mateIn2") == "Mate em 2"
    # A lista fechada do agente (documentação, seção 8) tem os 10 temas.
    assert len(TEMAS_DO_AGENTE) == 10


# -- validar_lances -------------------------------------------------------------

def test_validar_lances_independentes():
    r = tb.validar_lances(INICIAL, ["e4", "Cf3", "g1f3", "Ke2", "Nf6", "xyz"])
    assert [x["legal"] for x in r] == [True, True, True, False, False, False]
    assert (r[1]["san"], r[1]["san_pt"], r[1]["uci"]) == ("Nf3", "Cf3", "g1f3")


def test_validar_lances_em_sequencia():
    r = tb.validar_lances(INICIAL, ["1. e4", "e5", "Cf3", "Nc6", "Bb5"], em_sequencia=True)
    assert all(x["legal"] for x in r)
    assert [x["san"] for x in r] == ["e4", "e5", "Nf3", "Nc6", "Bb5"]


def test_validar_lances_sequencia_interrompe_no_ilegal():
    r = tb.validar_lances(INICIAL, ["e4", "e4", "Nf3"], em_sequencia=True)
    assert [x["legal"] for x in r] == [True, False, False]
    assert "não testado" in r[2]["motivo"]


def test_fen_invalido():
    with pytest.raises(ValueError, match="FEN inválido"):
        tb.validar_lances("isto não é fen", ["e4"])


# -- descrever_posicao ----------------------------------------------------------

def test_descrever_garfo_de_cavalo():
    # Cavalo branco em e5 pode ir a f7 atacando dama d8 e torre h8.
    fen = "r2qk2r/ppp2ppp/8/4N3/8/8/PPP2PPP/R3K2R w KQkq - 0 1"
    d = tb.descrever_posicao(fen)
    garfos = {g["lance"]: g for g in d["para_quem_joga"]["garfos_possiveis"]}
    assert "Nxf7" in garfos
    assert set(garfos["Nxf7"]["ataca"]) >= {"dama em d8", "torre em h8"}


def test_descrever_cravada_absoluta():
    # Depois de ...d6, o bispo em b5 crava o cavalo c6 contra o rei e8 (b5-c6-d7-e8).
    fen2 = "r1bqkbnr/ppp2ppp/2np4/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 4"
    d2 = tb.descrever_posicao(fen2)
    assert {"atacante": "bispo em b5", "cor_atacante": "white", "peca_da_frente": "cavalo em c6",
            "peca_de_tras": "rei em e8", "tipo": "absoluta"} in d2["cravadas"]


def test_descrever_peca_pendurada_e_mate_em_1():
    # Mate do corredor disponível (Re8#) e dama preta pendurada em d5.
    fen = "6k1/5ppp/8/3q4/8/8/5PPP/4R1K1 w - - 0 1"
    d = tb.descrever_posicao(fen)
    assert d["para_quem_joga"]["mate_em_1"] == ["Re8#"]
    assert d["vez"] == "white"
    assert d["material"]["saldo_brancas"] == 5 - 9


def test_descrever_xeque_mate():
    fen = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
    d = tb.descrever_posicao(fen)
    assert d["xeque_mate"] and d["em_xeque"]
    assert d["dando_xeque"] == ["dama em h4"]
    assert d["para_quem_joga"]["lances_legais"] == 0
