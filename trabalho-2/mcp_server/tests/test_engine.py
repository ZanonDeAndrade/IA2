import asyncio
import json
import os
import signal

import chess
import pytest

from agent.mcp import Ferramentas, sessao_mcp
from agent.validator import validar_resposta_async
from evaluation.dataset import carregar_dataset
from evaluation.primeira_explicacao import _linha_motor
from mcp_server.tests.test_board import AFOGAMENTO, MATE_EM_UM, XEQUE_MATE
from mcp_server.tools import engine


@pytest.fixture
def stockfish():
    if not os.getenv("STOCKFISH_PATH"):
        pytest.skip("configure STOCKFISH_PATH para testar com Stockfish real")
    yield
    engine._encerrar_motor(aguardar=True)


@pytest.mark.parametrize("fen", ["inválido", "8/8/8/8/8/8/8/8 w - - 0 1"])
def test_fen_invalido_independe_de_motor(fen, monkeypatch):
    monkeypatch.delenv("STOCKFISH_PATH", raising=False)
    with pytest.raises(ValueError, match="FEN"):
        engine.analisar_posicao(fen)


@pytest.mark.parametrize(("profundidade", "multipv"), [(0, 3), (18, 0), (True, 3)])
def test_parametros_invalidos(profundidade, multipv):
    with pytest.raises(ValueError, match="inteiros positivos"):
        engine.analisar_posicao(chess.STARTING_FEN, profundidade, multipv)


def test_motor_indisponivel(monkeypatch, tmp_path):
    monkeypatch.delenv("STOCKFISH_PATH", raising=False)
    with pytest.raises(RuntimeError, match="Configure STOCKFISH_PATH"):
        engine.analisar_posicao(chess.STARTING_FEN)
    monkeypatch.setenv("STOCKFISH_PATH", str(tmp_path / "stockfish"))
    with pytest.raises(RuntimeError, match="Falha no Stockfish"):
        engine.analisar_posicao(chess.STARTING_FEN)


def test_stockfish_real_posicao_inicial_multipv_e_reuso(stockfish):
    fen = chess.STARTING_FEN
    analise = engine.analisar_posicao(fen, profundidade=6)
    assert json.loads(json.dumps(analise)) == analise
    variantes = analise["melhores_lances"]
    assert analise["perspectiva"] == "white"
    assert len({variante["uci"] for variante in variantes}) == len(variantes) == 3
    assert analise["linha_principal"] == variantes[0]["linha"]
    assert analise["avaliacao"] == variantes[0]["avaliacao"]
    for variante in variantes:
        tabuleiro = chess.Board(fen)
        assert variante["uci"] == tabuleiro.parse_san(variante["san"]).uci()
        assert variante["linha"][0] == variante["san"]
        for san in variante["linha"]:
            lance = tabuleiro.parse_san(san)
            assert lance in tabuleiro.legal_moves and tabuleiro.san(lance) == san
            tabuleiro.push(lance)
    _, motor = engine._motor_ativo
    assert len(engine.analisar_posicao(fen, 4, 1)["melhores_lances"]) == 1
    assert engine._motor_ativo[1] is motor


@pytest.mark.parametrize(("lado", "cor", "sinal"), [("w", "white", 1), ("b", "black", -1)])
def test_stockfish_real_cp_e_perspectiva(stockfish, lado, cor, sinal):
    fen = f"4k3/pppppppp/8/8/8/8/PPPPPPPP/R3K3 {lado} - - 0 1"
    analise = engine.analisar_posicao(fen, 6, 1)
    assert analise["perspectiva"] == cor
    assert analise["avaliacao"]["tipo"] == "cp"
    assert analise["avaliacao"]["valor"] * sinal > 0


@pytest.mark.parametrize(("fen", "avaliacao"), [
    (XEQUE_MATE, {"tipo": "mate", "valor": 0, "a_favor": False}),
    (AFOGAMENTO, {"tipo": "cp", "valor": 0}),
])
def test_stockfish_real_posicao_terminal(stockfish, fen, avaliacao):
    analise = engine.analisar_posicao(fen, 6)
    assert analise == {
        "perspectiva": "black", "avaliacao": avaliacao, "melhores_lances": [], "linha_principal": [],
    }


@pytest.mark.parametrize(("fen", "valor", "a_favor"), [
    (MATE_EM_UM, 1, True),
    ("7k/8/5K2/6Q1/8/8/8/8 b - - 0 1", -1, False),
])
def test_stockfish_real_mate_forcado(stockfish, fen, valor, a_favor):
    analise = engine.analisar_posicao(fen, 6, 3)
    assert analise["avaliacao"] == {"tipo": "mate", "valor": valor, "a_favor": a_favor}
    assert analise["linha_principal"][-1].endswith("#")
    assert len(analise["melhores_lances"]) == min(3, chess.Board(fen).legal_moves.count())


@pytest.mark.skipif(not hasattr(signal, "SIGSTOP"), reason="requer sinais POSIX")
def test_stockfish_real_timeout_descarta_processo_e_recupera(stockfish, monkeypatch):
    fen = chess.STARTING_FEN
    engine.analisar_posicao(fen, 4, 1)
    _, anterior = engine._motor_ativo
    pid = anterior.transport.get_pid()
    try:
        with monkeypatch.context() as config:
            config.setattr(anterior, "timeout", 0.2)
            config.setattr(engine, "_TEMPO_BUSCA", 0.1)
            os.kill(pid, signal.SIGSTOP)
            with pytest.raises(TimeoutError, match="comunicação UCI"):
                engine.analisar_posicao(fen, 4, 1)
        assert engine._motor_ativo is None
        assert anterior.returncode.result(timeout=3) != 0
    finally:
        if not anterior.returncode.done():
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
    assert engine.analisar_posicao(fen, 4, 1)["linha_principal"]
    assert engine._motor_ativo[1] is not anterior


def test_ferramentas_reais_via_fastmcp_com_cliente_do_agente(stockfish, monkeypatch):
    monkeypatch.setenv("MCP_URL", "")
    item = carregar_dataset()[0]
    tabuleiro = chess.Board(item["fen"])
    fen_antes = tabuleiro.fen()
    tabuleiro.push_san(item["lance_jogado"])

    async def consultar():
        async with sessao_mcp() as disponiveis:
            ferramentas = Ferramentas(disponiveis)
            assert set(ferramentas.disponiveis) == {
                "analisar_posicao", "analisar_partida", "validar_lances", "descrever_posicao",
                "buscar_partidas", "buscar_puzzles", "buscar_conceitos", "jogar_stockfish",
            }
            motor = await ferramentas.chamar("analisar_posicao", fen=fen_antes, profundidade=8, multipv=3)
            assert motor["perspectiva"] == "black"
            assert len(motor["melhores_lances"]) == 3
            linha = _linha_motor(fen_antes, motor)
            assert linha == motor["linha_principal"]
            antes = await ferramentas.chamar("descrever_posicao", fen=fen_antes)
            depois = await ferramentas.chamar("descrever_posicao", fen=tabuleiro.fen())
            assert antes["lado_a_jogar"] == "black" and depois["lado_a_jogar"] == "white"
            assert {"cor": "black", "tipo": "torre", "casa": "d8"} in antes["pecas"]
            assert {"cor": "black", "tipo": "torre", "casa": "d2"} in depois["pecas"]
            resultado = await validar_resposta_async(
                " ".join(linha), fen_antes, linha, validar_lances=ferramentas.validar,
            )
            assert resultado["valida"]
            for ferramenta in ("analisar_posicao", "descrever_posicao"):
                with pytest.raises(RuntimeError, match=ferramenta):
                    await ferramentas.chamar(ferramenta, fen="inválido")

    asyncio.run(consultar())
