"""Ferramentas do tabuleiro: validação de lances e descrição factual da posição.

Tudo aqui é calculado com ``python-chess``, sem opinião e sem motor. É a base
do validador do agente (``agent/validator.py``).
"""


def validar_lances(fen: str, lances: list[str]) -> list[dict]:
    """Verifica se cada lance é legal na posição dada.

    Args:
        fen: posição em notação FEN.
        lances: lista de lances em SAN ou UCI.

    Returns:
        Lista com um dict por lance: ``{"lance": str, "legal": bool, "san": str}``.
        O campo ``san`` traz o lance normalizado (presente só quando legal).

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def descrever_posicao(fen: str) -> dict:
    """Descreve os fatos de uma posição, sem avaliação.

    Args:
        fen: posição em notação FEN.

    Returns:
        dict com material de cada lado, peças atacadas e indefesas, peças
        cravadas, xeques possíveis e exposição do rei (lado a jogar incluso).

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError
