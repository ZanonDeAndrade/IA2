import json
from contextlib import closing
from pathlib import Path
import os

import chess
from fastapi.testclient import TestClient
import pytest

from backend import db
from backend.main import app
from backend.services import perfil_explicacao
from data.scripts.download_puzzles import salvar_sqlite

RAIZ = Path(__file__).resolve().parents[2]
PGN = '[White "alice"]\n[Black "bob"]\n[WhiteElo "1500"]\n\n1. f3 e5 2. g4 Qh4# 0-1'


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "api.sqlite"))
    monkeypatch.setenv("MCP_URL", "")
    monkeypatch.setenv("MCP_HEALTH_URL", "")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("CHESSCOM_USER_AGENT", "")
    monkeypatch.setenv("PUZZLES_DB", str(tmp_path / "puzzles.sqlite"))
    with TestClient(app) as client:
        yield client


def test_validacao_e_openapi(cliente, monkeypatch):
    assert cliente.get("/healthz").json() == {"status": "ok"}
    with monkeypatch.context() as config:
        config.setenv("MCP_HEALTH_URL", "http://127.0.0.1:1/healthz")
        assert cliente.get("/healthz").status_code == 503
    assert cliente.get("/openapi.json").status_code == 200
    assert cliente.post("/api/partidas/importar", content=b"x" * (1024 * 1024 + 1)).status_code == 413
    assert cliente.post("/api/partidas/importar", json={"pgn": "inválido"}).status_code == 422
    resposta = cliente.post("/api/partidas/importar", json={"usuario": "alice"})
    assert resposta.status_code == 503 and "CHESSCOM_USER_AGENT" in resposta.json()["detail"]
    assert cliente.get("/api/partidas/ausente").status_code == 404
    assert cliente.post("/api/partidas/ausente/analisar").status_code == 404
    assert cliente.get("/api/tarefas/ausente").status_code == 404
    assert cliente.post("/api/chat", json={"fen": "inválido", "pergunta": "Qual a posição?"}).status_code == 422
    assert cliente.post("/api/explicar", json={"fen": chess.STARTING_FEN, "lance_jogado": "Qz9"}).status_code == 422
    vazio = cliente.get("/api/relatorio/novo").json()
    assert vazio["partidas_analisadas"] == 0 and vazio["rating_estimado"] is None
    assert vazio["puzzles_recomendados"] == vazio["temas_fracos"] == []


def test_pgn_mcp_stockfish_cache_e_relatorio(cliente):
    if not os.getenv("STOCKFISH_PATH"):
        pytest.skip("STOCKFISH_PATH requerido")
    fonte = RAIZ / "evaluation" / "lichess_candidatos.jsonl"
    salvar_sqlite((json.loads(linha)["row"] for linha in fonte.read_text().splitlines()), os.environ["PUZZLES_DB"])
    importada = cliente.post("/api/partidas/importar", json={"pgn": PGN})
    assert importada.status_code == 201
    id_ = importada.json()["partidas"][0]["id"]
    assert cliente.post("/api/partidas/importar", json={"pgn": PGN}).json()["partidas"][0]["id"] == id_
    assert cliente.get(f"/api/partidas/{id_}").json()["lances"] == []
    caminho = f"/api/partidas/{id_}/analisar"
    tarefa = cliente.post(caminho)
    assert tarefa.status_code == 202
    tarefa_id = tarefa.json()["tarefa_id"]
    progresso = cliente.get(f"/api/tarefas/{tarefa_id}").json()
    assert progresso["status"] == "concluida" and progresso["progresso"]["percentual"] == 100
    assert cliente.post(caminho).json()["tarefa_id"] == tarefa_id
    partida = cliente.get(f"/api/partidas/{id_}").json()
    assert len(partida["lances"]) == 4 and len(partida["curva_avaliacao"]) == 5
    assert partida["curva_avaliacao"][-1]["avaliacao"] == {"tipo": "mate", "valor": 0, "a_favor": False}
    lance = partida["lances"][2]
    assert lance["classe"] == "erro_grave"
    resposta = cliente.post("/api/explicar", json={"fen": lance["fen_antes"], "lance_jogado": lance["uci"]})
    assert resposta.status_code == 200
    explicacao = resposta.json()
    assert explicacao["lance_jogado"] == "g4" and explicacao["validada"] and explicacao["fallback"]
    assert "validar_lances" in explicacao["ferramentas_usadas"]
    chat = cliente.post("/api/chat", json={"fen": chess.STARTING_FEN, "pergunta": "Qual o melhor lance?"}).json()
    assert not chat["validada"] and chat["status"] == "indisponivel"
    antes = cliente.get("/api/relatorio/alice").json()
    assert antes["partidas_analisadas"] == 1 and antes["erros_sem_tema"] >= 1 and antes["puzzles_recomendados"]
    # Exercita a agregação com uma explicação persistida em fixture. O fluxo
    # acima rodou com Stockfish, MCP e validador reais e LLM ausente.
    with closing(db.conectar()) as conn:
        db.salvar_explicacao(conn, lance["fen_antes"], lance["san"],
                            {**explicacao, "tema": "mate", "validada": True, "fallback": False}, perfil_explicacao())
    relatorio = cliente.get("/api/relatorio/alice").json()
    assert relatorio["temas_fracos"][0]["tema"] == "mate"
    assert relatorio["puzzles_personalizados_por_tema"]
    assert all("mate" in puzzle["temas"] for puzzle in relatorio["puzzles_recomendados"])
    assert cliente.get(f"/api/partidas/{id_}").json()["lances"][2]["explicacao"]["tema"] == "mate"


def test_tarefa_falha_com_motor_ausente(cliente, monkeypatch):
    monkeypatch.setenv("STOCKFISH_PATH", "/nao-existe/stockfish")
    id_ = cliente.post("/api/partidas/importar", json={"pgn": PGN}).json()["partidas"][0]["id"]
    tarefa_id = cliente.post(f"/api/partidas/{id_}/analisar").json()["tarefa_id"]
    tarefa = cliente.get(f"/api/tarefas/{tarefa_id}").json()
    assert tarefa["status"] == "erro" and tarefa["erro"] and tarefa["resultado"] is None


@pytest.mark.skipif(not os.getenv("LANCE_TESTE_MCP_RAG"), reason="requer embeddings e MCP reais")
def test_api_grafos_com_modelo_fixture_e_ferramentas_reais(cliente, tmp_path, monkeypatch):
    if not os.getenv("STOCKFISH_PATH"):
        pytest.skip("STOCKFISH_PATH requerido")
    from langchain_core.messages import AIMessage, ToolMessage

    from agent import graph
    from knowledge_base.index import indexar

    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("LLM_MODEL", "fixture-de-contrato")
    assert indexar() == 30

    class ModeloFixture:
        def bind_tools(self, ferramentas):
            assert any(tool.name == "descrever_posicao" for tool in ferramentas)
            return self

        async def ainvoke(self, mensagens):
            if isinstance(mensagens[-1], ToolMessage):
                fatos = json.loads(mensagens[-1].content)
                assert fatos["lado_a_jogar"] == "black"
                return AIMessage(content="As pretas têm a vez.")
            dados = json.loads(mensagens[-1].content)
            if "temas_permitidos" in dados:
                assert dados["fatos"]["antes"]["lado_a_jogar"] == "black"
                assert dados["fatos"]["depois"]["lado_a_jogar"] == "white"
                return AIMessage(content="garfo")
            if "ficha" in dados:
                assert dados["ficha"]["arquivo"] == "knowledge_base/garfo.md"
                return AIMessage(content=json.dumps({
                    "aconteceu": "A torre mudou de casa", "motivo": "A jogada alterou as ameaças",
                    "licao": "Confira ameaças simultâneas antes de jogar",
                }))
            return AIMessage(content="", tool_calls=[
                {"name": "descrever_posicao", "args": {"fen": dados["fen"]}, "id": "descricao-fixture"},
            ])

    monkeypatch.setattr(graph, "_modelo", ModeloFixture)
    item = json.loads((RAIZ / "evaluation" / "dataset.jsonl").read_text().splitlines()[0])
    entrada = {"fen": item["fen"], "lance_jogado": item["lance_jogado"]}
    explicacao = cliente.post("/api/explicar", json=entrada).json()
    assert explicacao["validada"] and not explicacao["fallback"]
    assert explicacao["ficha"]["id"] == "garfo" and "validar_lances" in explicacao["ferramentas_usadas"]
    assert cliente.post("/api/explicar", json=entrada).json()["cache"]
    chat = cliente.post("/api/chat", json={"fen": item["fen"], "pergunta": "Quem tem a vez?"}).json()
    assert chat["validada"] and chat["resposta"] == "As pretas têm a vez."
    assert [tool["nome"] for tool in chat["ferramentas_usadas"]] == ["descrever_posicao"]


def test_reinicio_preserva_dados_e_marca_tarefa_interrompida(cliente):
    from mcp_server.tools.engine import perfil_analise

    id_ = cliente.post("/api/partidas/importar", json={"pgn": PGN}).json()["partidas"][0]["id"]
    with closing(db.conectar()) as conn:
        tarefa_id, criada = db.iniciar_tarefa(conn, id_, perfil_analise())
        assert criada
        assert db.iniciar_tarefa(conn, id_, perfil_analise()) == (tarefa_id, False)
    with TestClient(app) as reiniciada:
        assert reiniciada.get(f"/api/partidas/{id_}").json()["pgn"] == PGN
        assert reiniciada.get(f"/api/tarefas/{tarefa_id}").json()["status"] == "erro"
