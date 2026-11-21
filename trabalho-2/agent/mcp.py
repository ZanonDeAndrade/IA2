"""Sessão MCP utilizada pelos dois modos do agente."""

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import json
import logging
import os
from pathlib import Path
import sys
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

RAIZ = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger(__name__)
_ERROS_PUBLICOS = {
    "CHESSCOM_USUARIO_INEXISTENTE", "CHESSCOM_USER_AGENT_AUSENTE", "CHESSCOM_INDISPONIVEL",
    "PUZZLES_BASE_AUSENTE", "PUZZLES_BASE_INVALIDA",
}


class ErroFerramenta(RuntimeError):
    """Código explícito de erro de uma fonte pública."""


def _cliente() -> MultiServerMCPClient:
    load_dotenv(RAIZ / ".env")
    url = os.getenv("MCP_URL")
    if url:
        conexao = {"transport": "streamable_http", "url": url}
    else:
        variaveis = (
            "STOCKFISH_PATH", "CHESSCOM_USER_AGENT", "CHROMA_PATH", "EMBEDDING_MODEL", "HF_HOME", "HF_HUB_OFFLINE",
            "SQLITE_PATH", "PUZZLES_DB", "ANALISE_PROFUNDIDADE", "ANALISE_REVISAO_MOTOR",
        )
        conexao = {
            "transport": "stdio", "command": sys.executable,
            "args": ["-m", "mcp_server.server"], "cwd": str(RAIZ),
            "env": {nome: os.environ[nome] for nome in variaveis if nome in os.environ},
        }
    conexao["session_kwargs"] = {"read_timeout_seconds": timedelta(seconds=180)}
    return MultiServerMCPClient({"lance-a-lance": conexao})


async def carregar_ferramentas_mcp() -> list[BaseTool]:
    """Lista as ferramentas via adapter; as chamadas posteriores abrem suas sessões."""
    return await _cliente().get_tools()


@asynccontextmanager
async def sessao_mcp():
    async with _cliente().session("lance-a-lance") as sessao:
        yield await load_mcp_tools(sessao)


class Ferramentas:
    """Executa ferramentas conhecidas, normaliza as respostas e registra as chamadas."""

    def __init__(self, ferramentas: list[BaseTool]):
        self.disponiveis = {ferramenta.name: ferramenta for ferramenta in ferramentas}
        self.usadas: list[dict] = []

    async def chamar(self, nome: str, **argumentos):
        self.usadas.append({"nome": nome, "argumentos": argumentos})
        LOGGER.info("Chamando ferramenta MCP %s", nome)
        try:
            ferramenta = self.disponiveis[nome]
            resposta = await asyncio.wait_for(ferramenta.ainvoke({
                "type": "tool_call", "name": nome, "args": argumentos, "id": str(uuid4()),
            }), timeout=180 if nome == "analisar_partida" else 40 if nome == "buscar_partidas" else 20)
            if not isinstance(resposta, ToolMessage):
                raise ValueError("Ferramenta MCP retornou erro.")
            if resposta.status == "error":
                if nome in {"buscar_partidas", "buscar_puzzles"}:
                    codigo = resposta.text.strip()
                    if codigo in _ERROS_PUBLICOS:
                        raise ErroFerramenta(codigo)
                raise ValueError("Ferramenta MCP retornou erro.")
            if artefato := resposta.artifact:
                dados = artefato["structured_content"]
                return dados["result"] if set(dados) == {"result"} else dados
            if not isinstance(resposta.content, list):
                return json.loads(resposta.content)
            resultados = [json.loads(bloco["text"]) for bloco in resposta.content if bloco["type"] == "text"]
            if nome in {"validar_lances", "buscar_conceitos", "analisar_partida", "buscar_partidas", "buscar_puzzles"}:
                return resultados[0] if len(resultados) == 1 and isinstance(resultados[0], list) else resultados
            if len(resultados) == 1:
                return resultados[0]
            raise ValueError("Resposta MCP sem JSON utilizável.")
        except ErroFerramenta:
            raise
        except Exception as erro:
            LOGGER.warning("Falha na ferramenta MCP %s (%s)", nome, type(erro).__name__)
            raise RuntimeError(f"Ferramenta indisponível: {nome}.") from erro

    async def validar(self, fen: str, lances: list[str]) -> list[dict]:
        return await self.chamar("validar_lances", fen=fen, lances=lances)
