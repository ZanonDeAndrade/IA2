import json
from pathlib import Path
import sqlite3

import chess
import chess.pgn
import httpx
import pytest
from fastmcp.exceptions import ToolError

from data.scripts.download_puzzles import salvar_sqlite
from mcp_server.tools import chesscom, engine
from mcp_server.tools.pgn import ler_partida
from mcp_server.tools.puzzles import buscar_puzzles

RAIZ = Path(__file__).resolve().parents[2]
PGN = '[White "alice"]\n[Black "bob"]\n\n1. e4 e5 2. Nf3 Nc6 *'


def test_pgn_recusa_lance_ilegal_nulo_e_multiplas_partidas():
    for pgn in ("1. e4 e5 2. Bxh8 *", "1. -- e5 *", "1. e4 texto_inválido *", PGN + "\n\n" + PGN):
        with pytest.raises(ValueError):
            ler_partida(pgn)


def test_normalizacao_mate_zero_e_perda():
    antes = {"perspectiva": "black", "avaliacao": {"tipo": "cp", "valor": 0}}
    depois = {"perspectiva": "white", "avaliacao": {"tipo": "mate", "valor": 0, "a_favor": True}}
    resultado = engine.dados_classificacao(antes, depois, "black")
    assert resultado["avaliacao_depois"] == {"tipo": "mate", "valor": 0, "a_favor": False}
    assert resultado["queda"] == 50 and resultado["classe"] == "erro_grave"


def test_partida_real_perspectiva_e_cache(tmp_path, monkeypatch):
    import os
    if not os.getenv("STOCKFISH_PATH"):
        pytest.skip("STOCKFISH_PATH requerido")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "lance.sqlite"))
    monkeypatch.setenv("ANALISE_PROFUNDIDADE", "6")
    brancas = engine.analisar_partida(PGN, "white")
    todas = engine.analisar_partida(PGN, "ambas")
    assert brancas == todas[::2]
    assert [lance["indice"] for lance in todas] == [1, 2, 3, 4]
    assert all(lance["perspectiva"] == lance["cor"] for lance in todas)
    assert todas[0]["avaliacao_depois"]["valor"] == -todas[1]["avaliacao_antes"]["valor"]
    with sqlite3.connect(tmp_path / "lance.sqlite") as conn:
        assert conn.execute("SELECT count(*) FROM cache_mcp").fetchone()[0] == 5


@pytest.mark.parametrize(("ciclos", "cp_depois", "buscas"), [(2, -200, 2), (4, 0, 1)])
def test_partida_distingue_empate_automatico_de_reivindicavel(tmp_path, monkeypatch, ciclos, cp_depois, buscas):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "lance.sqlite"))
    tabuleiro = chess.Board()
    for uci in ["g1f3", "g8f6", "f3g1", "f6g8"] * ciclos:
        tabuleiro.push_uci(uci)
    pgn = str(chess.pgn.Game.from_board(tabuleiro))
    fens = []

    def avaliar(fen, _profundidade, _multipv):
        fens.append(fen)
        posicao = chess.Board(fen)
        lance = next(iter(posicao.legal_moves))
        return {"perspectiva": chess.COLOR_NAMES[posicao.turn], "avaliacao": {"tipo": "cp", "valor": 200},
                "linha_principal": [posicao.san(lance)], "melhores_lances": [{"uci": lance.uci()}]}

    monkeypatch.setattr(engine, "analisar_posicao", avaliar)
    ultimo, = engine.analisar_partida(pgn, "black", inicio=4 * ciclos - 1)
    assert ultimo["cp_depois"] == cp_depois
    assert len(fens) == buscas
    assert (tabuleiro.fen() in fens) is (ciclos == 2)


def test_puzzles_reais_filtrados_e_solucao(tmp_path, monkeypatch):
    fonte = RAIZ / "evaluation" / "lichess_candidatos.jsonl"
    caminho = tmp_path / "puzzles.sqlite"
    monkeypatch.setenv("PUZZLES_DB", str(caminho))
    with pytest.raises(ToolError, match="PUZZLES_BASE_AUSENTE"):
        buscar_puzzles([], 1000, 2000)
    dados = [json.loads(linha)["row"] for linha in fonte.read_text().splitlines()]
    assert salvar_sqlite([dados[0], *dados], str(caminho)) == len({row["PuzzleId"] for row in dados})
    achados = buscar_puzzles(["garfo"], 1000, 1900, 4)
    assert len(achados) == 4
    for puzzle in achados:
        assert "fork" in puzzle["temas"] and 1000 <= puzzle["rating"] <= 1900
        tabuleiro = chess.Board(puzzle["fen_origem"])
        tabuleiro.push_uci(puzzle["lance_preparatorio"])
        assert tabuleiro.fen() == puzzle["fen"]
        for lance in puzzle["solucao"]:
            tabuleiro.push_uci(lance)
    assert buscar_puzzles(["tema_inexistente"], 0, 4000) == []


def test_chesscom_paginas_ritmo_cache_e_404(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "mcp.sqlite"))
    monkeypatch.setenv("CHESSCOM_USER_AGENT", "teste-de-contrato")
    base = chesscom.BASE + "/alice/games"
    chamadas = []

    def jogo(id_, fim, ritmo):
        return {"pgn": PGN, "url": f"https://www.chess.com/game/live/{id_}", "end_time": fim,
                "time_class": ritmo, "rules": "chess",
                "white": {"username": "Alice", "rating": 1300},
                "black": {"username": "Bob", "rating": 1350}}

    def responder(request):
        url = str(request.url)
        chamadas.append(url)
        assert request.headers["User-Agent"] == "teste-de-contrato"
        if url == base + "/archives":
            return httpx.Response(200, json={"archives": [base + "/2020/01", base + "/2020/02", "https://example.invalid"]})
        if url.endswith("/2020/02"):
            return httpx.Response(200, json={"games": [jogo(2, 1000, "rapid"), jogo(3, 2000, "rapid"), jogo(5, 3000, "blitz")]})
        if url.endswith("/2020/01"):
            return httpx.Response(200, json={"games": [jogo(1, 500, "rapid")]})
        return httpx.Response(404)

    cliente = httpx.Client
    monkeypatch.setattr(chesscom.httpx, "Client",
                        lambda **kwargs: cliente(transport=httpx.MockTransport(responder), **kwargs))
    achadas = chesscom.buscar_partidas("Alice", 3, "rapid")
    assert [item["url"].rsplit("/", 1)[-1] for item in achadas] == ["3", "2", "1"]
    assert achadas[0]["adversario"] == "Bob" and achadas[0]["cor_do_jogador"] == "white"
    assert len(chamadas) == 3 and chesscom.buscar_partidas("alice", 3, "rapid") == achadas and len(chamadas) == 3
    with pytest.raises(ToolError, match="CHESSCOM_USUARIO_INEXISTENTE"):
        chesscom.buscar_partidas("inexistente")
