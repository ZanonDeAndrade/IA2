"""Ferramentas do tabuleiro: validação de lances e descrição factual da posição.

Tudo aqui é calculado com ``python-chess``, sem opinião e sem motor. É a base
do validador do agente (``agent/validator.py``).
"""

import chess

_NOMES_PECAS = {
    chess.PAWN: "peao", chess.KNIGHT: "cavalo", chess.BISHOP: "bispo",
    chess.ROOK: "torre", chess.QUEEN: "dama", chess.KING: "rei",
}


def _ler_fen(fen: str) -> chess.Board:
    if len(fen.split()) != 6:
        raise ValueError("Informe um FEN completo.")
    tabuleiro = chess.Board(fen)
    if not tabuleiro.is_valid():
        raise ValueError("Posição FEN inválida.")
    return tabuleiro


def _casas(quadrados) -> list[str]:
    return [chess.square_name(casa) for casa in quadrados]


def _notacao(tabuleiro: chess.Board, lance: chess.Move) -> dict[str, str]:
    return {"san": tabuleiro.san(lance), "uci": tabuleiro.uci(lance)}


def validar_lances(fen: str, lances: list[str]) -> list[dict]:
    """Verifica se cada lance é legal na posição dada.

    Args:
        fen: posição em notação FEN.
        lances: lista de lances em SAN ou UCI.

    Returns:
        Lista com um dict por lance: ``{"lance": str, "legal": bool, "san": str}``.
        O campo ``san`` traz o lance normalizado (presente só quando legal).

    Todos os itens são candidatos independentes no FEN informado. Para validar
    uma variante, o consumidor chama a ferramenta com o FEN de cada meio-lance.
    """
    tabuleiro = chess.Board(fen)
    if not tabuleiro.is_valid():
        raise ValueError("Posição FEN inválida.")
    resultado = []
    for lance in lances:
        item = {"lance": lance, "legal": False}
        try:
            movimento = tabuleiro.parse_san(lance.replace("×", "x"))
            if movimento in tabuleiro.legal_moves:
                item.update(legal=True, san=tabuleiro.san(movimento))
        except ValueError:
            pass
        resultado.append(item)
    return resultado


def descrever_posicao(fen: str) -> dict:
    """Descreve os fatos de uma posição, sem avaliação.

    As cores são white e black. O material é a contagem por tipo de peça.
    Ataques e defesas são geométricos no tabuleiro atual: incluem peças
    cravadas e não incluem en passant. Peças indefesas são as peças sem
    defensores da mesma cor, excluindo reis. Cravadas são as absolutas ao rei.

    Os dados dos reis incluem atacantes, casas adjacentes atacadas e peões
    aliados adjacentes. Essas casas usam a ocupação atual do tabuleiro. Os
    xeques possíveis são lances legais de quem tem a vez, em SAN e UCI.
    """
    tabuleiro = _ler_fen(fen)
    material = {cor: dict.fromkeys(_NOMES_PECAS.values(), 0) for cor in chess.COLOR_NAMES}
    pecas, atacadas, indefesas, cravadas = [], [], [], []
    for casa, peca in sorted(tabuleiro.piece_map().items()):
        cor, tipo = chess.COLOR_NAMES[peca.color], _NOMES_PECAS[peca.piece_type]
        material[cor][tipo] += 1
        registro = {"cor": cor, "tipo": tipo, "casa": chess.square_name(casa)}
        pecas.append(registro)
        atacantes = _casas(tabuleiro.attackers(not peca.color, casa))
        defensores = _casas(tabuleiro.attackers(peca.color, casa))
        if atacantes:
            atacadas.append({**registro, "atacantes": atacantes, "defensores": defensores})
        if not defensores and peca.piece_type != chess.KING:
            indefesas.append({**registro, "atacantes": atacantes})
        if tabuleiro.is_pinned(peca.color, casa):
            rei = tabuleiro.king(peca.color)
            sem_peca = tabuleiro.occupied & ~chess.BB_SQUARES[casa]
            por_tras = tabuleiro.attackers(not peca.color, rei, occupied=sem_peca)
            cravadores = por_tras - tabuleiro.attackers(not peca.color, rei)
            cravadas.append({**registro, "rei": chess.square_name(rei), "atacantes": _casas(cravadores)})

    reis = {}
    for lado in chess.COLORS:
        rei = tabuleiro.king(lado)
        em_volta = tabuleiro.attacks(rei)
        atacantes = _casas(tabuleiro.attackers(not lado, rei))
        casas_atacadas = (casa for casa in em_volta if tabuleiro.is_attacked_by(not lado, casa))
        reis[chess.COLOR_NAMES[lado]] = {
            "casa": chess.square_name(rei),
            "em_xeque": bool(atacantes),
            "atacantes": atacantes,
            "casas_adjacentes_atacadas": _casas(casas_atacadas),
            "peoes_adjacentes": _casas(em_volta & tabuleiro.pieces(chess.PAWN, lado)),
        }

    return {
        "lado_a_jogar": chess.COLOR_NAMES[tabuleiro.turn],
        "material": material,
        "pecas": pecas,
        "pecas_atacadas": atacadas,
        "pecas_indefesas": indefesas,
        "pecas_cravadas": cravadas,
        "xeques_possiveis": [_notacao(tabuleiro, lance) for lance in tabuleiro.legal_moves if tabuleiro.gives_check(lance)],
        "em_xeque": tabuleiro.is_check(),
        "xeque_mate": tabuleiro.is_checkmate(),
        "afogamento": tabuleiro.is_stalemate(),
        "reis": reis,
    }
