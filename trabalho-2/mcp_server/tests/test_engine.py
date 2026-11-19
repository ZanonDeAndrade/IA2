"""Testes das ferramentas do motor (precisam do Stockfish instalado)."""

import os
import shutil
import time

import pytest

from mcp_server.tools import engine

pytestmark = pytest.mark.skipif(
    not (os.getenv("STOCKFISH_PATH") or shutil.which("stockfish")),
    reason="Stockfish não instalado",
)

ITALIANA = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"

# Partida curta: 4.Nxe5? (imprecisão) e 5.Nxf7?? (erro grave), com mate no fim.
PGN = """[Event "Teste"]
[White "Brancas"]
[Black "Pretas"]
[Result "0-1"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Nd4 4. Nxe5 Qg5 5. Nxf7 Qxg2 6. Rf1 Qxe4+ 7. Be2 Nf3# 0-1
"""


def test_analisar_posicao_formato_e_tempo():
    inicio = time.perf_counter()
    r = engine.analisar_posicao(ITALIANA)
    assert time.perf_counter() - inicio < 2.5  # pronto quando < 2 s (+ abertura do motor)
    assert r["vez"] == "black"
    assert len(r["melhores_lances"]) == 3
    assert set(r["avaliacao"]) == {"cp", "mate"}
    # avaliação do lado a jogar (pretas) é o oposto da avaliação das brancas
    assert r["avaliacao"]["cp"] == -r["avaliacao_brancas"]["cp"]
    assert r["linha_principal"][0] == r["melhores_lances"][0]["san"]


def test_analisar_posicao_mate_em_1():
    r = engine.analisar_posicao("6k1/5ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1", profundidade=10, multipv=1)
    melhor = r["melhores_lances"][0]
    assert (melhor["san"], melhor["san_pt"], melhor["uci"]) == ("Re8#", "Te8#", "e1e8")
    assert r["avaliacao"]["mate"] == 1  # o lado a jogar dá mate em 1


def test_analisar_posicao_final_de_jogo():
    r = engine.analisar_posicao("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
    assert r["fim_de_jogo"] and r["avaliacao"]["cp"] < 0 and r["melhores_lances"] == []


def test_analisar_partida_classifica_erros(monkeypatch):
    monkeypatch.setenv("PROFUNDIDADE_PARTIDA", "12")
    monkeypatch.setenv("TEMPO_POR_LANCE", "0.3")
    chamadas = []
    lances = engine.analisar_partida(PGN, "white", progresso=lambda f, t: chamadas.append((f, t)))
    assert len(lances) == 14 and chamadas[-1] == (15, 15)
    assert [x["indice"] for x in lances] == list(range(1, 15))
    por_lance = {(x["numero"], x["cor"]): x for x in lances}
    nxf7 = por_lance[(5, "white")]
    assert nxf7["san"] == "Nxf7" and nxf7["classe"] == "erro_grave"
    # Bxf7+ e O-O ficam quase iguais para o motor; o importante é coerência entre os campos.
    assert nxf7["melhor_lance"] in {"Bxf7+", "O-O"} and nxf7["melhor_lance_uci"] in {"c4f7", "e1g1"}
    assert nxf7["linha_motor"][0] == nxf7["melhor_lance"]
    assert nxf7["chance_vitoria_antes"] - nxf7["chance_vitoria_depois"] == pytest.approx(nxf7["queda"], abs=0.02)
    # Lances das pretas não são classificados quando cor_do_jogador = white.
    assert all(x["classe"] is None and not x["do_jogador"] for x in lances if x["cor"] == "black")
    # Ponto de vista do jogador (brancas): levou mate no fim.
    assert lances[-1]["chance_vitoria_depois"] == 0.0


def test_analisar_partida_ponto_de_vista_das_pretas(monkeypatch):
    monkeypatch.setenv("PROFUNDIDADE_PARTIDA", "10")
    monkeypatch.setenv("TEMPO_POR_LANCE", "0.2")
    lances = engine.analisar_partida(PGN, "black")
    assert lances[-1]["chance_vitoria_depois"] == 100.0  # as pretas deram mate
    assert all(x["classe"] is not None for x in lances if x["cor"] == "black")


def test_analisar_partida_pgn_invalido():
    with pytest.raises(ValueError, match="PGN inválido"):
        engine.analisar_partida("isto não é PGN", "white")


def test_analisar_partida_cor_invalida():
    with pytest.raises(ValueError, match="cor_do_jogador"):
        engine.analisar_partida(PGN, "azuis")
