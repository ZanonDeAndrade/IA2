"""Testes de buscar_partidas (API do Chess.com simulada) e buscar_puzzles (base temporária)."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from mcp_server.tools import chesscom, puzzles

RAIZ = Path(__file__).resolve().parents[2]

PGN_CURTO = '[Event "Live"]\n[ECO "C50"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 1-0\n'


def _jogo(n, fim, time_class="blitz", rules="chess", branco="Marcelo", resultado_branco="win"):
    return {
        "url": f"https://www.chess.com/game/live/{n}",
        "pgn": PGN_CURTO,
        "end_time": fim,
        "time_class": time_class,
        "time_control": "180",
        "rules": rules,
        "eco": "https://www.chess.com/openings/Italian-Game-Giuoco-Piano-3...Bc5",
        "white": {"username": branco, "rating": 1200, "result": resultado_branco},
        "black": {"username": "rival" if branco == "Marcelo" else "Marcelo", "rating": 1250,
                  "result": "checkmated" if resultado_branco == "win" else "win"},
    }


ARQUIVOS = {
    "/pub/player/marcelo/games/archives": {"archives": [
        "https://api.chess.com/pub/player/marcelo/games/2020/01",
        "https://api.chess.com/pub/player/marcelo/games/2020/02",
    ]},
    "/pub/player/marcelo/games/2020/02": {"games": [
        _jogo(3, 300), _jogo(4, 400, rules="chess960"), _jogo(5, 500, time_class="rapid"),
    ]},
    "/pub/player/marcelo/games/2020/01": {"games": [
        _jogo(1, 100, branco="rival", resultado_branco="win"), _jogo(2, 200, resultado_branco="agreed"),
    ]},
}


@pytest.fixture
def cliente_falso(tmp_path):
    pedidos = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        if "User-Agent" not in request.headers:
            return httpx.Response(403)
        dados = ARQUIVOS.get(request.url.path)
        return httpx.Response(200, json=dados) if dados else httpx.Response(404, json={})

    cli = chesscom.ClienteChessCom(transport=httpx.MockTransport(responder),
                                   cache_path=tmp_path / "cache.sqlite", pausa_s=0)
    cli.pedidos = pedidos
    return cli


def test_buscar_partidas_ordem_filtro_e_formato(cliente_falso):
    r = chesscom.buscar_partidas("Marcelo", max=10, _cliente=cliente_falso)
    assert [p["id"] for p in r] == ["chesscom-5", "chesscom-3", "chesscom-2", "chesscom-1"]  # chess960 fora
    p = r[0]
    assert p["cor_do_jogador"] == "white" and p["resultado_do_jogador"] == "vitoria"
    assert p["adversario"] == "rival" and p["resultado"] == "1-0"
    assert p["abertura"] == "Italian Game Giuoco Piano"
    assert p["total_lances"] == 3 and p["data"] == "1970-01-01"
    por_id = {x["id"]: x for x in r}
    assert por_id["chesscom-2"]["resultado_do_jogador"] == "empate"
    assert por_id["chesscom-1"]["cor_do_jogador"] == "black"
    assert por_id["chesscom-1"]["resultado_do_jogador"] == "derrota"


@pytest.mark.parametrize("url, nome", [
    ("https://www.chess.com/openings/Italian-Game-Giuoco-Piano-3...Bc5", "Italian Game Giuoco Piano"),
    ("https://www.chess.com/openings/Closed-Sicilian-Defense-Fianchetto-Variation...5.d3-d6",
     "Closed Sicilian Defense Fianchetto Variation"),
    ("https://www.chess.com/openings/Owens-Defense", "Owens Defense"),
])
def test_nome_da_abertura(url, nome):
    assert chesscom._abertura("", url) == nome


def test_buscar_partidas_para_no_mes_suficiente(cliente_falso):
    r = chesscom.buscar_partidas("marcelo", max=2, _cliente=cliente_falso)
    assert len(r) == 2
    meses = [p.url.path for p in cliente_falso.pedidos if "/games/20" in p.url.path]
    assert meses == ["/pub/player/marcelo/games/2020/02"]  # não precisou do mês anterior


def test_buscar_partidas_ritmo_em_portugues(cliente_falso):
    r = chesscom.buscar_partidas("marcelo", max=10, ritmo="rápida", _cliente=cliente_falso)
    assert [p["id"] for p in r] == ["chesscom-5"]


def test_buscar_partidas_usa_cache(cliente_falso):
    chesscom.buscar_partidas("marcelo", max=10, _cliente=cliente_falso)
    n = len(cliente_falso.pedidos)
    chesscom.buscar_partidas("marcelo", max=10, _cliente=cliente_falso)
    assert len(cliente_falso.pedidos) == n  # tudo veio do cache


def test_buscar_partidas_usuario_inexistente(cliente_falso):
    with pytest.raises(chesscom.ErroChessCom, match="não encontrado"):
        chesscom.buscar_partidas("ninguem", _cliente=cliente_falso)


def test_buscar_partidas_usuario_invalido(cliente_falso):
    with pytest.raises(chesscom.ErroChessCom, match="inválido"):
        chesscom.buscar_partidas("../etc", _cliente=cliente_falso)


# -- puzzles ------------------------------------------------------------------

def _script_puzzles():
    caminho = RAIZ / "data" / "scripts" / "download_puzzles.py"
    spec = importlib.util.spec_from_file_location("download_puzzles", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


LINHAS = [
    # Puzzle real da Lichess (00008): o adversário joga Qxh2+?? ... aqui só importa o formato.
    {"PuzzleId": "00008", "FEN": "r6k/pp2r2p/4Rp1Q/3p4/8/1N1P2R1/PqP2bPP/7K b - - 0 24",
     "Moves": "f2g3 e6e7 b2b1 b3c1 b1c1 h6c1", "Rating": "1900", "RatingDeviation": "80",
     "Popularity": "95", "NbPlays": "1000", "Themes": "crushing hangingPiece long middlegame",
     "GameUrl": "https://lichess.org/787zsVup/black#47", "OpeningTags": ""},
    {"PuzzleId": "0000D", "FEN": "5rk1/1p3ppp/pq3b2/8/8/1P1Q1N2/P4PPP/3R2K1 w - - 2 27",
     "Moves": "d3d6 f8d8 d6d8 f6d8", "Rating": "1500", "RatingDeviation": "75",
     "Popularity": "96", "NbPlays": "2000", "Themes": "advantage endgame short fork",
     "GameUrl": "https://lichess.org/F8M8OS71#53", "OpeningTags": ""},
    {"PuzzleId": "0009B", "FEN": "r2qr1k1/b1p2ppp/pp4n1/P1P1p3/4P1n1/B2P2Pb/3NBP1P/RN1QR1K1 b - - 1 16",
     "Moves": "b6c5 e2g4 h3g4 d1g4", "Rating": "1100", "RatingDeviation": "75",
     "Popularity": "85", "NbPlays": "500", "Themes": "advantage middlegame short pin fork",
     "GameUrl": "https://lichess.org/4MWQCxQ6/black#31", "OpeningTags": ""},
]


@pytest.fixture
def base_puzzles(tmp_path, monkeypatch):
    destino = tmp_path / "puzzles.sqlite"
    _script_puzzles().salvar(LINHAS, destino)
    monkeypatch.setenv("PUZZLES_DB", str(destino))
    return destino


def test_amostragem_filtra_rating():
    modulo = _script_puzzles()
    amostra, validos = modulo.amostrar(LINHAS, 10, 1000, 1600, 50, 100, 42)
    assert validos == 2 and {p["PuzzleId"] for p in amostra} == {"0000D", "0009B"}


def test_buscar_puzzles_por_tema_em_portugues(base_puzzles):
    r = puzzles.buscar_puzzles(["garfo", "cravada"], 600, 2200, 5)
    assert r[0]["id"] == "0009B"  # tem os dois temas
    assert {p["id"] for p in r} == {"0009B", "0000D"}


def test_buscar_puzzles_formato(base_puzzles):
    p = puzzles.buscar_puzzles(["peca_pendurada", "fork"], 1400, 1600, 5)[0]
    assert p["id"] == "0000D"
    assert p["fen"] == LINHAS[1]["FEN"] and p["solucao"] == ["d3d6", "f8d8", "d6d8", "f6d8"]
    assert p["url"] == "https://lichess.org/training/0000D"
    assert p["lance_adversario"] == "Qd6"  # o 1º lance é do adversário
    assert p["vez"] == "black"
    assert p["solucao_san"] == ["Rd8", "Qxd8+", "Bxd8"] and p["solucao_san_pt"][0] == "Td8"
    assert p["tema_agente"] == "garfo"
    assert p["temas_label"] == ["Garfo"]  # sem fase/tamanho (endgame, short, advantage)


def test_buscar_puzzles_faixa_de_rating(base_puzzles):
    assert [p["id"] for p in puzzles.buscar_puzzles(["fork"], 600, 1200, 5)] == ["0009B"]
    assert puzzles.buscar_puzzles(["fork"], 2100, 2200, 5) == []


def test_buscar_puzzles_sem_base(tmp_path, monkeypatch):
    monkeypatch.setenv("PUZZLES_DB", str(tmp_path / "nao_existe.sqlite"))
    with pytest.raises(puzzles.ErroPuzzles, match="download_puzzles.py"):
        puzzles.buscar_puzzles(["fork"], 600, 2200)


def test_json_serializavel(base_puzzles):
    json.dumps(puzzles.buscar_puzzles([], 600, 2200, 3))
