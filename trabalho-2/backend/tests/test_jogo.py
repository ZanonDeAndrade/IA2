from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import StringIO
import os
from threading import Event
from time import time
from uuid import uuid4

import chess
import chess.pgn
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from backend import db, services
from backend.jogo import repositorio, servico
from backend.jogo.modelos import Configuracoes, JogoSalvo, SelecaoMotor
from backend.jogo.tabuleiro import exportar
from backend.main import app
from mcp_server.tools.board import reproduzir_lances

BASE = "/api/jogo"
TORRE = "7k/8/8/8/8/8/R7/7K w - - {meios} {numero}"
CICLO = ["g1f3", "g8f6", "f3g1", "f6g8"]


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "jogo.sqlite"))
    monkeypatch.setenv("MCP_URL", "")
    monkeypatch.setenv("MCP_HEALTH_URL", "")
    monkeypatch.setenv("LLM_MODEL", "")
    with TestClient(app) as client:
        yield client


@pytest.fixture
def resposta_controlada(monkeypatch):
    async def responder(nome, *, fen_inicial, lances, dificuldade):
        assert nome == "jogar_stockfish"
        tabuleiro = reproduzir_lances(fen_inicial, lances)
        return {"uci": next(iter(tabuleiro.legal_moves)).uci(), "motor": "Stockfish de teste", "opcoes_uci": {}}

    monkeypatch.setattr(services, "mcp", responder)
    return responder


def semear(fen=chess.STARTING_FEN, cor="white", movimentos=(), **configuracoes):
    jogo = JogoSalvo(id=uuid4().hex, criado_em=db.agora(), cor_do_jogador=cor, dificuldade="iniciante",
                     fen_inicial=fen, fen=fen, configuracoes=Configuracoes(analise_automatica=False, **configuracoes))
    tabuleiro = chess.Board(fen)
    for uci in movimentos:
        selecao = None if chess.COLOR_NAMES[tabuleiro.turn] == cor else SelecaoMotor(motor="Teste", opcoes_uci={})
        servico.aplicar(jogo, tabuleiro, tabuleiro.parse_uci(uci), selecao)
    exportar(jogo, tabuleiro)
    repositorio.criar(jogo)
    return f"{BASE}/{jogo.id}"


def test_inicio_de_brancas_e_validacoes(cliente):
    assert cliente.get(f"{BASE}/ausente").status_code == 404
    assert cliente.post(f"{BASE}/iniciar", json={"dificuldade": "outro"}).status_code == 422
    inicio = cliente.post(f"{BASE}/iniciar", json={})
    assert inicio.status_code == 201
    jogo = inicio.json()
    assert jogo["fen"] == chess.STARTING_FEN and jogo["versao"] == 0
    assert jogo["cor_da_ia"] == "black" and jogo["vez"] == "jogador"
    assert len(jogo["lances_legais"]) == 20 and not jogo["lances"]
    rota = f"{BASE}/{jogo['id']}"
    assert cliente.get(rota + "/resultado").status_code == 409
    for uci in ("e7e5", "e2e5", "e2e4q", "0000", "e4"):
        assert cliente.post(rota + "/mover", json={"lance": uci, "versao": 0}).status_code == 422
    assert cliente.get(rota).json() == jogo
    assert cliente.post(rota + "/reivindicar-empate", json={"versao": 0}).status_code == 422


def test_partidas_da_sessao_separadas_do_usuario_do_relatorio(cliente):
    sessao = {"X-Sessao-Jogo": "a" * 64}
    outra = {"X-Sessao-Jogo": "b" * 64}
    entrada = {"usuario": "mesmo_nome"}
    antigo = cliente.post(BASE + "/iniciar", json=entrada).json()
    primeiro = cliente.post(BASE + "/iniciar", json=entrada, headers=sessao).json()
    separado = cliente.post(BASE + "/iniciar", json=entrada, headers=outra).json()
    segundo = cliente.post(BASE + "/iniciar", json=entrada, headers=sessao).json()
    assert antigo["usuario"] is None
    assert primeiro["usuario"] == segundo["usuario"] and primeiro["usuario"].startswith("treino-")
    assert separado["usuario"] != primeiro["usuario"]
    assert cliente.post(f"{BASE}/{segundo['id']}/desistir", json={"versao": 0}).status_code == 200

    rota = BASE + "/partidas"
    assert cliente.get(rota).status_code == 422
    assert cliente.get(rota, headers={"X-Sessao-Jogo": "mesmo_nome"}).status_code == 422
    resposta = cliente.get(rota, headers=sessao)
    assert resposta.headers["cache-control"] == "no-store"
    mais_recente, restante = resposta.json()["partidas"]
    assert (mais_recente["id"], mais_recente["status"], mais_recente["resultado"]) == (
        segundo["id"], "encerrada", "0-1",
    )
    assert restante["id"] == primeiro["id"]
    assert cliente.get(rota + "?limite=1&deslocamento=1", headers=sessao).json()["partidas"] == [restante]
    assert [item["id"] for item in cliente.get(rota, headers=outra).json()["partidas"]] == [separado["id"]]
    with TestClient(app) as reiniciada:
        assert reiniciada.get(rota, headers=sessao).json() == resposta.json()
        assert reiniciada.get(f"{BASE}/{antigo['id']}").json() == antigo


def test_lance_do_jogador_fora_do_turno(cliente):
    rota = semear(cor="black")
    assert cliente.get(rota).json()["vez"] == "ia"
    assert cliente.post(rota + "/mover", json={"lance": "e7e5", "versao": 0}).status_code == 409


def test_desistencia_sem_lances(cliente):
    rota = semear()
    resposta = cliente.post(rota + "/desistir", json={"versao": 0})
    assert resposta.status_code == 200
    fim = resposta.json()
    assert fim["resultado"] == "0-1" and fim["partida_analise_id"] is None
    assert chess.pgn.read_game(StringIO(fim["pgn"])).headers["Result"] == "0-1"
    assert cliente.get(rota + "/historico").json()["lances"] == []


@pytest.mark.parametrize(("fen", "uci", "san", "casa_vazia"), [
    ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1g1", "O-O", chess.E1),
    ("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "e5d6", "exd6", chess.D5),
])
def test_roque_e_en_passant(cliente, resposta_controlada, fen, uci, san, casa_vazia):
    rota = semear(fen)
    r = cliente.post(rota + "/mover", json={"lance": uci, "versao": 0})
    assert r.status_code == 200
    jogador, ia = r.json()["lances"]
    assert jogador["san"] == san and not chess.Board(jogador["fen_depois"]).piece_at(casa_vazia)
    assert jogador["fen_depois"] == ia["fen_antes"] and ia["autor"] == "ia"


def test_promocao_explicita_e_material_insuficiente(cliente):
    rota = semear("7k/P7/8/8/8/8/8/7K w - - 0 1")
    assert cliente.post(rota + "/mover", json={"lance": "a7a8", "versao": 0}).status_code == 422
    r = cliente.post(rota + "/mover", json={"lance": "a7a8n", "versao": 0})
    assert r.status_code == 200
    jogo = r.json()
    assert jogo["resultado"] == "1/2-1/2" and jogo["motivo"] == "material_insuficiente"
    assert len(jogo["lances"]) == 1 and chess.Board(jogo["fen"]).piece_at(chess.A8) == chess.Piece(chess.KNIGHT, True)


def test_rei_em_xeque_mate_e_afogamento(cliente):
    rota = semear("4r2k/8/8/8/8/8/P7/4K3 w - - 0 1")
    assert cliente.get(rota).json()["em_xeque"]
    assert cliente.post(rota + "/mover", json={"lance": "a2a3", "versao": 0}).status_code == 422

    for uci, motivo, resultado in (("g6g7", "xeque_mate", "1-0"), ("g6f7", "afogamento", "1/2-1/2")):
        rota = semear("7k/8/5KQ1/8/8/8/8/8 w - - 0 1")
        r = cliente.post(rota + "/mover", json={"lance": uci, "versao": 0})
        assert r.status_code == 200
        jogo = r.json()
        assert jogo["motivo"] == motivo and jogo["resultado"] == resultado and jogo["vez"] is None
        assert jogo["partida_analise_id"] and len(jogo["lances"]) == 1
        assert cliente.post(rota + "/mover", json={"lance": "h8h7", "versao": 1}).status_code == 409


@pytest.mark.parametrize(("fen", "cor", "movimentos", "uci", "motivo"), [
    (chess.STARTING_FEN, "white", CICLO * 2, None, "tripla_repeticao"),
    (chess.STARTING_FEN, "black", (CICLO * 2)[:-1], "f6g8", "tripla_repeticao"),
    (TORRE.format(meios=100, numero=51), "white", [], None, "regra_50_lances"),
    (TORRE.format(meios=99, numero=50), "white", [], "a2a3", "regra_50_lances"),
])
def test_empate_reivindicado_agora_e_por_lance(cliente, fen, cor, movimentos, uci, motivo):
    rota = semear(fen, cor, movimentos)
    anterior = cliente.get(rota).json()
    assert anterior["status"] == "em_andamento"
    empate = anterior["empate_reivindicavel"]
    assert (empate["agora"] if uci is None else empate["por_lance"][uci]) == motivo
    fim = cliente.post(rota + "/reivindicar-empate", json={"lance": uci, "versao": 0}).json()
    assert fim["status"] == "encerrada" and fim["resultado"] == "1/2-1/2" and fim["motivo"] == motivo
    assert fim["lances"] == anterior["lances"] and fim["fen"] == anterior["fen"]


@pytest.mark.parametrize(("fen", "cor", "movimentos", "uci", "motivo"), [
    (chess.STARTING_FEN, "black", (CICLO * 4)[:-1], "f6g8", "repeticao_quintupla"),
    (TORRE.format(meios=149, numero=75), "white", [], "a2a3", "regra_75_lances"),
])
def test_empate_automatico(cliente, fen, cor, movimentos, uci, motivo):
    rota = semear(fen, cor, movimentos)
    r = cliente.post(rota + "/mover", json={"lance": uci, "versao": 0})
    assert r.status_code == 200
    assert r.json()["motivo"] == motivo and r.json()["resultado"] == "1/2-1/2"


def test_concorrencia_e_retry_na_mesma_versao(cliente, resposta_controlada, monkeypatch):
    import asyncio

    rota = semear()
    iniciou, liberar = Event(), Event()

    async def responder(*args, **kwargs):
        iniciou.set()
        assert await asyncio.to_thread(liberar.wait, 5)
        return await resposta_controlada(*args, **kwargs)

    monkeypatch.setattr(services, "mcp", responder)
    with ThreadPoolExecutor() as pool:
        futuro = pool.submit(cliente.post, rota + "/mover", json={"lance": "e2e4", "versao": 0})
        try:
            assert iniciou.wait(5)
            durante = cliente.get(rota).json()
            assert durante["processando"] and durante["versao"] == 0 and not durante["lances"]
            assert cliente.post(rota + "/mover", json={"lance": "d2d4", "versao": 0}).status_code == 409
            assert cliente.post(rota + "/desistir", json={"versao": 0}).status_code == 409
        finally:
            liberar.set()
        final = futuro.result(timeout=10)
    assert final.status_code == 200
    assert final.json()["versao"] == 1 and len(final.json()["lances"]) == 2
    assert cliente.post(rota + "/mover", json={"lance": "e2e4", "versao": 0}).status_code == 409


def test_falha_do_motor_e_reserva_abandonada(cliente, resposta_controlada, monkeypatch):
    async def indisponivel(*args, **kwargs):
        raise HTTPException(503, "Stockfish indisponível")

    rota = semear()
    with monkeypatch.context() as config:
        config.setattr(services, "mcp", indisponivel)
        assert cliente.post(rota + "/mover", json={"lance": "e2e4", "versao": 0}).status_code == 503
    original = cliente.get(rota).json()
    assert not original["lances"] and not original["processando"] and original["fen"] == chess.STARTING_FEN
    with closing(db.conectar()) as conn, conn:
        conn.execute("UPDATE jogos SET reserva='abandonada', reservada_ate=? WHERE id=?", (time() - 1, original["id"]))
    r = cliente.post(rota + "/mover", json={"lance": "e2e4", "versao": 0})
    assert r.status_code == 200 and r.json()["versao"] == 1


@pytest.mark.skipif(not os.getenv("STOCKFISH_PATH"), reason="requer o Stockfish real")
def test_stockfish_real_feedback_pgn_revisao_e_reinicio(cliente, monkeypatch):
    r = cliente.post(BASE + "/iniciar", headers={"X-Sessao-Jogo": "a" * 64},
                     json={"cor_do_jogador": "black", "dificuldade": "iniciante", "frequencia_explicacoes": "todos"})
    assert r.status_code == 201
    inicio = r.json()
    primeiro, = inicio["lances"]
    assert primeiro["autor"] == "ia" and primeiro["cor"] == "white" and inicio["vez"] == "jogador"
    assert inicio["versao"] == 0 and inicio["cor_da_vez"] == "black"
    rota = f"{BASE}/{inicio['id']}"
    assert cliente.post(rota + "/historico/1/avaliar", json={"versao": 0}).status_code == 422
    uci = inicio["lances_legais"][0]
    r = cliente.post(rota + "/mover", json={"lance": uci, "versao": 0})
    assert r.status_code == 200
    em_jogo = r.json()
    lance = em_jogo["lances"][1]
    analise = lance["avaliacao"]
    assert em_jogo["lances"][2]["autor"] == "ia" and lance["sugerir_explicacao"]
    assert analise["perspectiva"] == "black" and analise["uci"] == uci
    assert analise["linha_motor"][0] == analise["melhor_lance"] and analise["fen_antes"] == inicio["fen"]
    r = cliente.post(rota + "/historico/2/explicar")
    assert r.status_code == 200 and r.json()["validada"] and r.json()["fallback"]
    assert r.json()["melhor_lance"] == analise["melhor_lance"]
    solicitados = []
    chamar = services.Ferramentas.chamar

    async def registrar(ferramentas, nome, **argumentos):
        if nome == "analisar_partida":
            inicio = argumentos["inicio"]
            solicitados.extend(range(inicio + 1, inicio + argumentos["limite"] + 1))
        return await chamar(ferramentas, nome, **argumentos)

    monkeypatch.setattr(services.Ferramentas, "chamar", registrar)
    r = cliente.post(rota + "/desistir", json={"versao": 1})
    assert r.status_code == 200
    fim = r.json()
    assert fim["resultado"] == "1-0" and fim["motivo"] == "desistencia"
    jogo = chess.pgn.read_game(StringIO(fim["pgn"]))
    assert not jogo.errors and jogo.headers["Result"] == "1-0" and jogo.end().board().fen() == fim["fen"]
    assert "Melhor alternativa" in jogo.variation(0).variation(0).comment
    revisao = f"/api/partidas/{fim['partida_analise_id']}"
    assert cliente.post(revisao + "/analisar").status_code == 202
    tradicional = cliente.get(revisao).json()
    assert tradicional["status_analise"] == "concluida" and tradicional["lances"][1] == analise
    assert tradicional["usuario"] == inicio["usuario"]
    assert solicitados == [1, 3]
    with closing(db.conectar()) as conn:
        assert db.avaliacoes_do_treino(conn, tradicional["id"], lance["perfil_avaliacao"]) == {2: analise}
        assert db.avaliacoes_do_treino(conn, tradicional["id"], "outro-perfil") == {}
    with TestClient(app) as reiniciada:
        assert reiniciada.get(rota).json() == fim
        assert reiniciada.get(rota + "/historico").json()["lances"] == fim["lances"]
        assert reiniciada.get(rota + "/resultado").json()["partida_analise_id"] == tradicional["id"]


@pytest.mark.skipif(not os.getenv("STOCKFISH_PATH"), reason="requer o Stockfish real")
def test_avaliacao_sob_demanda_sem_treinador(cliente, monkeypatch):
    r = cliente.post(BASE + "/iniciar", json={"analise_automatica": False, "modo_treinador": False,
                                               "modo_assistencia": "intensivo"})
    rota = f"{BASE}/{r.json()['id']}"
    r = cliente.post(rota + "/mover", json={"lance": "e2e4", "versao": 0})
    assert r.status_code == 200 and r.json()["lances"][0]["avaliacao"] is None
    assert cliente.post(rota + "/historico/1/explicar").status_code == 409
    assert cliente.post(rota + "/dica", json={"versao": 1, "nivel": 1}).status_code == 409
    assert cliente.post(rota + "/chat", json={"versao": 1, "pergunta": "Qual lance joguei?"}).status_code == 409
    fim = cliente.post(rota + "/desistir", json={"versao": 1}).json()

    async def motor_fora(*args, **kwargs):
        pytest.fail("O lance já foi avaliado na revisão.")

    monkeypatch.setattr(services, "mcp", motor_fora)
    r = cliente.post(rota + "/historico/1/avaliar", json={"versao": fim["versao"]})
    assert r.status_code == 200 and r.json()["estatisticas"]["lances_do_jogador_analisados"] == 1
    assert r.json()["lances"][0]["avaliacao"]["classe"] == "aceitavel"
    revisao = cliente.get(f"/api/partidas/{fim['partida_analise_id']}").json()
    assert revisao["pgn"] == r.json()["pgn"] and "Melhor alternativa" in revisao["pgn"]
    assert revisao["lances"][0] == r.json()["lances"][0]["avaliacao"]
