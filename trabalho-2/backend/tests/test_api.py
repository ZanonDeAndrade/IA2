"""Testes de ponta a ponta da API: FastAPI -> cliente MCP (em memória) -> ferramentas.

Precisam do Stockfish. A API do Chess.com é simulada; o resto é real.
"""

import os
import shutil

import httpx
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not (os.getenv("STOCKFISH_PATH") or shutil.which("stockfish")),
    reason="Stockfish não instalado",
)

PGN = """[Event "Teste"]
[White "Marcelo"]
[Black "Rival"]
[Result "0-1"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Nd4 4. Nxe5 Qg5 5. Nxf7 Qxg2 6. Rf1 Qxe4+ 7. Be2 Nf3# 0-1
"""


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "teste.sqlite"))
    monkeypatch.setenv("MCP_URL", "")
    monkeypatch.setenv("PUZZLES_DB", str(tmp_path / "sem_puzzles.sqlite"))
    monkeypatch.setenv("TEMPO_POR_LANCE", "0.2")
    from mcp_server import server
    monkeypatch.setattr(server, "LOG_ARQUIVO", tmp_path / "mcp.jsonl")

    from mcp_server.tools import chesscom

    def responder(request: httpx.Request) -> httpx.Response:
        caminho = request.url.path
        if caminho == "/pub/player/marcelo/games/archives":
            return httpx.Response(200, json={"archives": [
                "https://api.chess.com/pub/player/marcelo/games/2020/01"]})
        if caminho == "/pub/player/marcelo/games/2020/01":
            return httpx.Response(200, json={"games": [{
                "url": "https://www.chess.com/game/live/777", "pgn": PGN, "end_time": 1_600_000_000,
                "time_class": "blitz", "time_control": "180", "rules": "chess",
                "white": {"username": "Marcelo", "rating": 1100, "result": "checkmated"},
                "black": {"username": "Rival", "rating": 1150, "result": "win"}}]})
        return httpx.Response(404)

    falso = chesscom.ClienteChessCom(transport=httpx.MockTransport(responder),
                                     cache_path=tmp_path / "chesscom.sqlite", pausa_s=0)
    monkeypatch.setattr(chesscom, "_cliente", falso)

    from backend.main import app
    with TestClient(app) as c:
        yield c


def test_importar_pgn_analisar_e_obter(api):
    r = api.post("/api/partidas/importar", json={"pgn": PGN, "cor_do_jogador": "white"})
    assert r.status_code == 201
    partida = r.json()["partidas"][0]
    assert partida["status_analise"] == "pendente" and partida["resultado_do_jogador"] == "derrota"
    assert partida["adversario"] == "Rival" and partida["total_lances"] == 7

    r = api.post(f"/api/partidas/{partida['id']}/analisar")
    assert r.status_code == 202 and r.json()["tarefa_id"].startswith("tarefa-")
    tarefa = api.get(f"/api/tarefas/{r.json()['tarefa_id']}").json()
    assert tarefa["status"] == "concluida", tarefa  # TestClient roda a tarefa ao fim da requisição
    assert tarefa["progresso"] == {"lance_atual": 15, "total_lances": 15, "percentual": 100.0}

    p = api.get(f"/api/partidas/{partida['id']}").json()
    assert p["status_analise"] == "concluida" and p["resumo"]["erros_graves"] >= 1
    assert all(l["cor"] == "white" for l in p["lances"])  # só os lances do jogador
    assert len(p["todos_lances"]) == 14 and len(p["curva_avaliacao"]) == 14
    nxf7 = next(l for l in p["lances"] if l["san"] == "Nxf7")
    assert nxf7["classe"] == "erro_grave" and nxf7["melhor_lance"] in {"Bxf7+", "O-O"}
    exp = nxf7["explicacao"]
    assert exp["origem"] in {"motor", "agente"} and exp["validada"] is True
    assert "Nxf7" in exp["texto"] and exp["tema_label"]
    assert next(l for l in p["lances"] if l["classe"] == "aceitavel")["explicacao"] is None

    # Segunda chamada usa o cache.
    r = api.post(f"/api/partidas/{partida['id']}/analisar")
    assert r.json()["status"] == "concluida" and r.json()["etapa"] == "cache"


def test_importar_chesscom_e_relatorio(api):
    r = api.post("/api/partidas/importar", json={"usuario": "Marcelo", "max": 5})
    assert r.status_code == 201
    partidas = r.json()["partidas"]
    assert [p["id"] for p in partidas] == ["chesscom-777"]
    assert partidas[0]["cor_do_jogador"] == "white" and partidas[0]["resultado"] == "0-1"

    api.post("/api/partidas/chesscom-777/analisar")
    rel = api.get("/api/relatorio/marcelo").json()
    assert rel["partidas_analisadas"] == 1 and rel["rating_estimado"] == 1100
    assert rel["evolucao"][0]["erros_graves"] >= 1
    assert rel["puzzles_recomendados"] == []  # base de puzzles ausente neste teste
    for t in rel["temas_fracos"]:
        assert set(t) == {"tema", "tema_label", "erros"}


def test_explicar_lance(api):
    fen = "r1b1kbnr/pppp1ppp/8/4N1q1/2BnP3/8/PPPP1PPP/RNBQK2R w KQkq - 1 5"
    r = api.post("/api/explicar", json={"fen": fen, "lance_jogado": "Nxf7"})
    assert r.status_code == 200, r.text
    corpo = r.json()
    # O melhor lance pode variar entre lances quase iguais (Bxf7+, O-O); basta não ser o erro.
    assert corpo["classe"] == "erro_grave" and corpo["melhor_lance"] not in (None, "Nxf7")
    assert corpo["lance_jogado"] == "Nxf7" and corpo["cache"] is False
    assert {"tema", "tema_label", "texto", "ficha", "ferramentas_usadas", "tentativas", "validada"} <= set(corpo)
    assert api.post("/api/explicar", json={"fen": fen, "lance_jogado": "Cxf7"}).json()["cache"] is True


def test_erros_claros(api):
    assert api.post("/api/partidas/importar", json={"pgn": "bobagem"}).status_code == 400
    assert api.post("/api/partidas/importar", json={}).status_code == 422
    assert api.post("/api/partidas/importar", json={"usuario": "ninguem"}).status_code == 404
    assert api.post("/api/partidas/nao-existe/analisar").status_code == 404
    assert api.get("/api/tarefas/nao-existe").status_code == 404
    r = api.post("/api/explicar", json={"fen": "8/8/8/8/8/8/8/K1k5 w - - 0 1", "lance_jogado": "Ka3"})
    assert r.status_code == 400 and "não é legal" in r.json()["detail"]


def test_chat_sem_agente_responde_503(api):
    from backend import agente
    if agente.agente_disponivel():
        pytest.skip("agente configurado")
    r = api.post("/api/chat", json={"fen": "8/8/8/8/8/8/8/K1k5 w - - 0 1", "pergunta": "Quem ganha?"})
    assert r.status_code == 503


def test_saude(api):
    assert api.get("/api/saude").json()["mcp"] is True
