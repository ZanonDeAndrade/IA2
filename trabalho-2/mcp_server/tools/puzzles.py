"""Ferramenta de recomendação de puzzles da base aberta da Lichess (CC0).

Consulta o recorte da base salvo em SQLite por ``data/scripts/download_puzzles.py``.
Os temas usam os nomes em inglês da coluna ``Themes`` (``fork``, ``pin``,
``hangingPiece``...); a tradução para português fica em um dicionário
compartilhado com o agente.
"""


def buscar_puzzles(
    temas: list[str],
    rating_min: int,
    rating_max: int,
    quantidade: int = 5,
) -> list[dict]:
    """Busca puzzles por tema e faixa de rating.

    Args:
        temas: temas da Lichess (ex.: ``["fork", "hangingPiece"]``).
        rating_min: rating mínimo do puzzle.
        rating_max: rating máximo do puzzle.
        quantidade: quantidade de puzzles devolvidos (padrão 5).

    Returns:
        Lista de puzzles, cada um com ``id``, ``fen``, ``solucao`` (lances em UCI),
        ``rating``, ``temas`` e ``url`` (``https://lichess.org/training/{id}``).

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError
