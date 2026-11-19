"""Ferramenta de recomendação de puzzles da base aberta da Lichess (CC0).

Consulta o recorte da base salvo em SQLite por ``data/scripts/download_puzzles.py``.
Os temas usam os nomes em inglês da coluna ``Themes`` (``fork``, ``pin``,
``hangingPiece``...); a tradução para português fica em ``temas.py``, que é
compartilhado com o agente.

Formato da Lichess: o FEN do puzzle é a posição ANTES do lance do adversário; o
primeiro lance de ``solucao`` é o do adversário e o resto é a resposta do
jogador. Para facilitar a interface, cada puzzle também traz ``fen_jogador``
(posição que o jogador resolve) e a solução em SAN.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import chess

from mcp_server.tools.notacao import san_pt
from mcp_server.tools.temas import TEMAS_NAO_TATICOS, para_lichess, rotulo, tema_do_agente


class ErroPuzzles(RuntimeError):
    pass


def caminho_base() -> Path:
    padrao = Path(__file__).resolve().parents[2] / "data" / "puzzles.sqlite"
    return Path(os.getenv("PUZZLES_DB", padrao))


def _conectar() -> sqlite3.Connection:
    caminho = caminho_base()
    if not caminho.exists():
        raise ErroPuzzles(
            f"Base de puzzles não encontrada em {caminho}. "
            "Rode: python data/scripts/download_puzzles.py"
        )
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def formatar(linha: sqlite3.Row) -> dict:
    board = chess.Board(linha["fen"])
    uci = linha["moves"].split()
    adversario = chess.Move.from_uci(uci[0])
    lance_adversario = board.san(adversario)
    board.push(adversario)
    fen_jogador = board.fen()
    vez = "white" if board.turn else "black"

    solucao_san = []
    for u in uci[1:]:
        mv = chess.Move.from_uci(u)
        solucao_san.append(board.san(mv))
        board.push(mv)

    temas = linha["themes"].split()
    return {
        "id": linha["id"],
        "fen": linha["fen"],
        "solucao": uci,
        "rating": linha["rating"],
        "temas": temas,
        "temas_label": [rotulo(t) for t in temas if t not in TEMAS_NAO_TATICOS],
        "url": f"https://lichess.org/training/{linha['id']}",
        "fen_jogador": fen_jogador,
        "vez": vez,
        "lance_adversario": lance_adversario,
        "solucao_san": solucao_san,
        "solucao_san_pt": [san_pt(s) for s in solucao_san],
        "tema_agente": tema_do_agente(temas),
        "popularidade": linha["popularity"],
        "partida_original": linha["game_url"],
    }


def buscar_puzzles(
    temas: list[str],
    rating_min: int,
    rating_max: int,
    quantidade: int = 5,
    excluir: list[str] | None = None,
) -> list[dict]:
    """Busca puzzles por tema e faixa de rating.

    Os puzzles com mais temas pedidos vêm primeiro; o resto é aleatório, para
    cada chamada sugerir exercícios diferentes.

    Args:
        temas: temas da Lichess (``["fork", "hangingPiece"]``), em português
            (``garfo``) ou ids do agente (``peca_pendurada``). Vazio = qualquer tema.
        rating_min: rating mínimo do puzzle.
        rating_max: rating máximo do puzzle.
        quantidade: quantidade de puzzles devolvidos (1 a 50, padrão 5).
        excluir: ids de puzzles que não devem voltar.

    Returns:
        Lista de puzzles, cada um com ``id``, ``fen``, ``solucao`` (UCI, o primeiro
        é do adversário), ``rating``, ``temas``, ``temas_label``, ``url``
        (``https://lichess.org/training/{id}``), ``fen_jogador`` e ``solucao_san``.
    """
    quantidade = max(1, min(int(quantidade), 50))
    rating_min, rating_max = sorted((int(rating_min), int(rating_max)))
    temas_en = [para_lichess(t) for t in (temas or []) if t and t.strip()]
    excluir = excluir or []
    filtro_excluir = f"AND p.id NOT IN ({','.join('?' * len(excluir))})" if excluir else ""

    with _conectar() as con:
        if temas_en:
            sql = f"""
                SELECT p.*, COUNT(*) AS acertos
                FROM puzzle_temas t JOIN puzzles p ON p.id = t.puzzle_id
                WHERE t.tema IN ({','.join('?' * len(temas_en))})
                  AND p.rating BETWEEN ? AND ? {filtro_excluir}
                GROUP BY p.id
                ORDER BY acertos DESC, RANDOM()
                LIMIT ?"""
            params = [*temas_en, rating_min, rating_max, *excluir, quantidade]
        else:
            sql = f"""
                SELECT p.* FROM puzzles p
                WHERE p.rating BETWEEN ? AND ? {filtro_excluir}
                ORDER BY RANDOM() LIMIT ?"""
            params = [rating_min, rating_max, *excluir, quantidade]
        linhas = con.execute(sql, params).fetchall()
    return [formatar(l) for l in linhas]
