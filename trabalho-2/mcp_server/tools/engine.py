"""Ferramentas do motor: avaliação de posições e partidas com o Stockfish.

O binário é acionado pelo ``python-chess`` via UCI (caminho em ``STOCKFISH_PATH``).
Uma única instância do motor deve ser reaproveitada entre chamadas, com limite
de tempo por posição.
"""


def analisar_posicao(fen: str, profundidade: int = 18, multipv: int = 3) -> dict:
    """Avalia uma posição com o Stockfish.

    Args:
        fen: posição em notação FEN.
        profundidade: profundidade de busca do motor (padrão 18).
        multipv: quantidade de melhores lances devolvidos (padrão 3).

    Returns:
        dict com:
            - ``avaliacao``: centipeões (``cp``) ou mate (``mate``), do ponto de
              vista do lado a jogar;
            - ``melhores_lances``: os ``multipv`` melhores lances em SAN, cada um
              com sua avaliação;
            - ``linha_principal``: sequência de lances (SAN) da variante principal.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def analisar_partida(pgn: str, cor_do_jogador: str) -> list[dict]:
    """Analisa todos os lances do jogador em uma partida.

    Usa ``analisar_posicao`` antes e depois de cada lance do jogador, calcula a
    queda na chance de vitória e classifica o lance (ver ``agent/classifier.py``).
    O resultado deve ir para o cache (SQLite) para não reprocessar a partida.

    Args:
        pgn: partida completa em PGN.
        cor_do_jogador: ``"white"`` ou ``"black"``; só os lances dessa cor são
            classificados.

    Returns:
        Lista com um dict por lance do jogador: número do lance, SAN, FEN antes e
        depois, avaliação antes e depois, queda na chance de vitória,
        classificação (``aceitavel``, ``imprecisao``, ``erro``, ``erro_grave``)
        e melhor lance.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError
