"""Testes do servidor MCP em memória (cliente FastMCP, sem rede)."""

import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from mcp_server import server

FERRAMENTAS = {"analisar_posicao", "analisar_partida", "validar_lances", "descrever_posicao",
               "buscar_partidas", "buscar_puzzles", "buscar_conceitos"}


@pytest.fixture(autouse=True)
def log_temporario(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "LOG_ARQUIVO", tmp_path / "mcp_tools.jsonl")
    return tmp_path / "mcp_tools.jsonl"


async def test_sete_ferramentas_registradas():
    async with Client(server.mcp) as c:
        nomes = {t.name for t in await c.list_tools()}
    assert nomes == FERRAMENTAS


async def test_chamada_registrada_no_log(log_temporario):
    async with Client(server.mcp) as c:
        r = await c.call_tool("validar_lances", {
            "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "lances": ["e4"]})
    assert r.data[0]["legal"] is True
    registro = json.loads(log_temporario.read_text().strip().splitlines()[-1])
    assert registro["ferramenta"] == "validar_lances" and registro["ok"] is True


async def test_erro_vira_mensagem_clara(log_temporario):
    async with Client(server.mcp) as c:
        with pytest.raises(ToolError, match="FEN inválido"):
            await c.call_tool("descrever_posicao", {"fen": "bobagem"})
    registro = json.loads(log_temporario.read_text().strip().splitlines()[-1])
    assert registro["ok"] is False


async def test_buscar_conceitos_ainda_nao_implementada():
    """Enquanto o RAG não existir, a ferramenta responde com erro claro (não derruba o servidor)."""
    async with Client(server.mcp) as c:
        try:
            await c.call_tool("buscar_conceitos", {"pergunta": "garfo"})
        except ToolError as e:
            assert "ainda não foi implementada" in str(e)
