"""Servidor MCP do Lance a Lance.

Instância FastMCP que registra as sete ferramentas determinísticas usadas pelo
agente. Todas devolvem JSON e são a única fonte de fatos sobre o tabuleiro que
o LLM pode usar: ele nunca calcula lances, só interpreta o que as ferramentas
devolvem.

Ferramentas registradas:
    - analisar_posicao(fen, profundidade=18, multipv=3)
    - analisar_partida(pgn, cor_do_jogador)
    - validar_lances(fen, lances)
    - descrever_posicao(fen)
    - buscar_partidas(usuario, max=10, ritmo=None)
    - buscar_puzzles(temas, rating_min, rating_max, quantidade=5)
    - buscar_conceitos(pergunta, k=4)

Cada chamada fica registrada em ``logs/mcp_tools.jsonl`` (RNF06).

Execução (a partir de ``trabalho-2/``):
    python -m mcp_server.server                     # transporte stdio
    MCP_TRANSPORT=http python -m mcp_server.server  # HTTP em :8001/mcp (Docker)
    fastmcp dev mcp_server/server.py                # inspetor do FastMCP
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Annotated, Any, Callable

from pydantic import Field

# Permite rodar como arquivo (fastmcp dev mcp_server/server.py).
RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv  # noqa: E402
from fastmcp import Context, FastMCP  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402

from mcp_server.tools import board, chesscom, concepts, engine, puzzles  # noqa: E402

load_dotenv(RAIZ / ".env")

# --------------------------------------------------------------------------- #
# Log de cada chamada de ferramenta (RNF06)
# --------------------------------------------------------------------------- #

LOG_DIR = Path(os.getenv("LOG_DIR", RAIZ / "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_ARQUIVO = LOG_DIR / "mcp_tools.jsonl"

log = logging.getLogger("lance-a-lance.mcp")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), stream=sys.stderr,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Erros com mensagem pensada para o usuário: viram ToolError com o mesmo texto.
ERROS_DO_USUARIO = (ValueError, engine.ErroMotor, chesscom.ErroChessCom, puzzles.ErroPuzzles)


def _resumo(valor: Any, limite: int = 300) -> str:
    texto = json.dumps(valor, ensure_ascii=False, default=str)
    return texto if len(texto) <= limite else texto[:limite] + "…"


def _registrar(nome: str, args: dict, inicio: float, ok: bool, saida: Any = None,
               erro: str | None = None) -> None:
    registro = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ferramenta": nome,
        "argumentos": _resumo(args),
        "duracao_ms": round((time.perf_counter() - inicio) * 1000),
        "ok": ok,
    }
    if erro:
        registro["erro"] = erro
    else:
        registro["saida"] = _resumo(saida, 200)
    log.info("%s %s em %sms", nome, "ok" if ok else f"ERRO: {erro}", registro["duracao_ms"])
    with open(LOG_ARQUIVO, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def _converter_erro(nome: str, dados: dict, inicio: float, e: Exception) -> Exception:
    if isinstance(e, ERROS_DO_USUARIO):
        _registrar(nome, dados, inicio, False, erro=str(e))
        return ToolError(str(e))
    if isinstance(e, NotImplementedError):
        _registrar(nome, dados, inicio, False, erro="não implementada")
        return ToolError(f"A ferramenta {nome} ainda não foi implementada.")
    _registrar(nome, dados, inicio, False, erro=repr(e))
    return e


def com_log(func: Callable) -> Callable:
    """Registra a chamada e converte erros conhecidos em ToolError com mensagem clara."""
    nome = func.__name__

    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            inicio = time.perf_counter()
            dados = {k: v for k, v in kwargs.items() if k != "ctx"}
            try:
                saida = await func(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                novo = _converter_erro(nome, dados, inicio, e)
                if novo is e:
                    raise
                raise novo from e
            _registrar(nome, dados, inicio, True, saida)
            return saida
    else:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            inicio = time.perf_counter()
            try:
                saida = func(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                novo = _converter_erro(nome, kwargs, inicio, e)
                if novo is e:
                    raise
                raise novo from e
            _registrar(nome, kwargs, inicio, True, saida)
            return saida
    return wrapper


# --------------------------------------------------------------------------- #
# Ferramentas
# --------------------------------------------------------------------------- #

mcp = FastMCP(
    "lance-a-lance",
    instructions=(
        "Ferramentas de xadrez do Lance a Lance. Elas são a única fonte de fatos sobre "
        "posições: use-as em vez de calcular lances. Lances em SAN inglês (san) e "
        "português (san_pt); cores como 'white' e 'black'."
    ),
)

Fen = Annotated[str, Field(description="Posição em FEN.")]


@mcp.tool()
@com_log
def analisar_posicao(
    fen: Fen,
    profundidade: Annotated[int, Field(ge=1, le=30, description="Profundidade de busca do Stockfish.")] = 18,
    multipv: Annotated[int, Field(ge=1, le=5, description="Quantos melhores lances devolver.")] = 3,
) -> dict:
    """Avalia a posição com o Stockfish: avaliação (cp ou mate, do ponto de vista do
    lado a jogar), os melhores lances em SAN com suas avaliações e a linha principal."""
    return engine.analisar_posicao(fen, profundidade, multipv)


@mcp.tool()
@com_log
async def analisar_partida(
    pgn: Annotated[str, Field(description="Partida completa em PGN.")],
    cor_do_jogador: Annotated[str, Field(description="'white' ou 'black': só os lances dessa cor são classificados.")],
    ctx: Context | None = None,
) -> list[dict]:
    """Analisa a partida lance a lance com o Stockfish. Para cada meio-lance devolve
    as avaliações antes e depois (ponto de vista do jogador), a queda na chance de
    vitória, a classe (aceitavel, imprecisao, erro, erro_grave) e o melhor lance com
    a linha do motor. Envia progresso a cada posição analisada."""
    loop = asyncio.get_running_loop()
    ultimo = [0.0]

    def progresso(feito: int, total: int) -> None:
        if ctx is None:
            return
        agora = time.monotonic()
        if feito == total or agora - ultimo[0] > 0.25:  # no máximo 4 avisos por segundo
            ultimo[0] = agora
            asyncio.run_coroutine_threadsafe(
                ctx.report_progress(feito, total, f"posição {feito} de {total}"), loop)

    return await asyncio.to_thread(engine.analisar_partida, pgn, cor_do_jogador, progresso)


@mcp.tool()
@com_log
def validar_lances(
    fen: Fen,
    lances: Annotated[list[str], Field(description="Lances em SAN (Nf3 ou Cf3) ou UCI (g1f3).")],
    em_sequencia: Annotated[bool, Field(description="True se os lances formam uma linha jogada em sequência.")] = False,
    preferir: Annotated[str, Field(description="Notação usada quando um lance é ambíguo: 'en' ou 'pt'.")] = "en",
) -> list[dict]:
    """Verifica se cada lance é legal na posição e devolve o SAN normalizado.
    Base do validador do agente: nenhum lance citado ao usuário pode ser ilegal."""
    return board.validar_lances(fen, lances, em_sequencia, preferir)


@mcp.tool()
@com_log
def descrever_posicao(fen: Fen) -> dict:
    """Fatos objetivos da posição, calculados com python-chess (sem opinião): material,
    peças atacadas, penduradas e sem defesa, cravadas, espetos, xeques, capturas e garfos
    disponíveis, mate em 1 e segurança dos reis."""
    return board.descrever_posicao(fen)


@mcp.tool()
@com_log
def buscar_partidas(
    usuario: Annotated[str, Field(description="Nome de usuário no Chess.com.")],
    max: Annotated[int, Field(ge=1, le=50, description="Quantas partidas buscar.")] = 10,
    ritmo: Annotated[str | None, Field(description="bullet, blitz, rapid ou daily (opcional).")] = None,
) -> list[dict]:
    """Últimas partidas de xadrez padrão de um usuário do Chess.com (da mais recente
    para a mais antiga), com PGN, cores, resultado, ritmo e abertura."""
    return chesscom.buscar_partidas(usuario, max, ritmo)


@mcp.tool()
@com_log
def buscar_puzzles(
    temas: Annotated[list[str], Field(description="Temas da Lichess (fork), em português (garfo) ou ids do agente (peca_pendurada).")],
    rating_min: Annotated[int, Field(description="Rating mínimo do puzzle.")],
    rating_max: Annotated[int, Field(description="Rating máximo do puzzle.")],
    quantidade: Annotated[int, Field(ge=1, le=50)] = 5,
) -> list[dict]:
    """Puzzles da base aberta da Lichess com os temas pedidos e na faixa de rating,
    com FEN, solução, rating, temas e link."""
    return puzzles.buscar_puzzles(temas, rating_min, rating_max, quantidade)


@mcp.tool()
@com_log
def buscar_conceitos(
    pergunta: Annotated[str, Field(description="Pergunta ou tema em português.")],
    k: Annotated[int, Field(ge=1, le=10)] = 4,
) -> list[dict]:
    """Trechos das fichas de conceitos táticos e estratégicos (RAG no ChromaDB),
    com título, tema e arquivo, para fundamentar a explicação."""
    return concepts.buscar_conceitos(pergunta, k)


def main() -> None:
    """Sobe o servidor MCP (stdio por padrão; MCP_TRANSPORT=http para HTTP)."""
    if os.getenv("MCP_TRANSPORT", "stdio") == "http":
        mcp.run(transport="http", host=os.getenv("MCP_HOST", "0.0.0.0"),
                port=int(os.getenv("MCP_PORT", "8001")), show_banner=False)
    else:
        mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
