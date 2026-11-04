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

Execução (a partir de ``trabalho-2/``):
    python -m mcp_server.server          # transporte stdio
    fastmcp dev mcp_server/server.py     # inspetor do FastMCP
"""

from fastmcp import FastMCP

from mcp_server.tools.board import descrever_posicao, validar_lances
from mcp_server.tools.chesscom import buscar_partidas
from mcp_server.tools.concepts import buscar_conceitos
from mcp_server.tools.engine import analisar_partida, analisar_posicao
from mcp_server.tools.puzzles import buscar_puzzles

mcp = FastMCP("lance-a-lance")

FERRAMENTAS = (
    analisar_posicao,
    analisar_partida,
    validar_lances,
    descrever_posicao,
    buscar_partidas,
    buscar_puzzles,
    buscar_conceitos,
)

for ferramenta in FERRAMENTAS:
    mcp.tool()(ferramenta)


def main() -> None:
    """Sobe o servidor MCP (transporte stdio por padrão)."""
    mcp.run()


if __name__ == "__main__":
    main()
