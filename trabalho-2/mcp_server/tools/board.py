"""Ferramentas do tabuleiro: validação de lances e descrição factual da posição.

Tudo aqui é calculado com ``python-chess``, sem opinião e sem motor. É a base
do validador do agente (``agent/validator.py``).

`descrever_posicao` só devolve fatos calculados com python-chess, sem opinião:
material, peças atacadas e penduradas, cravadas, espetos, xeques, capturas,
garfos disponíveis, mate em 1 e segurança dos reis.
"""

from __future__ import annotations

from typing import Any

import chess

from mcp_server.tools.notacao import NOMES_PECAS, VALORES, interpretar_lance, san_pt

COR = {chess.WHITE: "white", chess.BLACK: "black"}
LIMITE_LISTA = 12  # máximo de itens em listas longas (xeques, capturas...)


def _board(fen: str) -> chess.Board:
    try:
        board = chess.Board(fen)
    except ValueError as e:
        raise ValueError(f"FEN inválido: {e}") from None
    if not board.is_valid():
        raise ValueError(f"Posição ilegal no FEN: {board.status()!r}")
    return board


# --------------------------------------------------------------------------- #
# validar_lances
# --------------------------------------------------------------------------- #

def validar_lances(fen: str, lances: list[str], em_sequencia: bool = False,
                   preferir: str = "en") -> list[dict]:
    """Verifica se cada lance é legal na posição dada.

    Aceita UCI (e2e4), SAN inglês (Nf3) e SAN português (Cf3), com ou sem número
    do lance e anotações (``12. Nf3!?``).

    Args:
        fen: posição em notação FEN.
        lances: lista de lances.
        em_sequencia: ``False`` testa cada lance na mesma posição; ``True`` trata
            a lista como uma linha (cada lance é jogado antes do próximo) e,
            depois do primeiro ilegal, os seguintes não são testados.
        preferir: notação que vence quando o texto é legal nas duas leituras
            ("R" = torre em inglês, rei em português): ``"en"`` ou ``"pt"``.

    Returns:
        Lista com um dict por lance: ``{"lance", "legal", "san", "san_pt", "uci"}``
        (``san``/``san_pt``/``uci`` só quando legal; ``motivo`` quando ilegal;
        ``ambiguo`` quando o lance foi lido nas duas notações).
    """
    board = _board(fen)
    resultado: list[dict] = []
    interrompido = False
    for lance in lances:
        if interrompido:
            resultado.append({"lance": lance, "legal": False, "motivo": "não testado: lance anterior ilegal"})
            continue
        mv, notacao, ambiguo = interpretar_lance(board, lance, preferir)
        if mv is None:
            item: dict[str, Any] = {"lance": lance, "legal": False,
                                    "motivo": "lance ilegal ou inexistente nesta posição"}
            interrompido = em_sequencia
        else:
            san = board.san(mv)
            item = {"lance": lance, "legal": True, "san": san, "san_pt": san_pt(san),
                    "uci": mv.uci(), "notacao_lida": notacao}
            if ambiguo:
                item["ambiguo"] = True
            if em_sequencia:
                board.push(mv)
        resultado.append(item)
    return resultado


# --------------------------------------------------------------------------- #
# descrever_posicao
# --------------------------------------------------------------------------- #

def _nome(board: chess.Board, sq: chess.Square) -> str:
    p = board.piece_at(sq)
    return f"{NOMES_PECAS[p.piece_type]} em {chess.square_name(sq)}"


def _peca(board: chess.Board, sq: chess.Square) -> dict[str, Any]:
    p = board.piece_at(sq)
    return {"peca": NOMES_PECAS[p.piece_type], "casa": chess.square_name(sq),
            "cor": COR[p.color], "valor": VALORES[p.piece_type]}


def _material(board: chess.Board) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for cor in (chess.WHITE, chess.BLACK):
        pecas = {NOMES_PECAS[t]: len(board.pieces(t, cor)) for t in
                 (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN)}
        pontos = sum(VALORES[t] * len(board.pieces(t, cor)) for t in VALORES)
        out[COR[cor]] = {"pecas": pecas, "pontos": pontos}
    out["saldo_brancas"] = out["white"]["pontos"] - out["black"]["pontos"]
    return out


def _atacadas(board: chess.Board) -> list[dict[str, Any]]:
    """Peças (exceto rei) atacadas pelo adversário, com atacantes e defensores."""
    lista = []
    for sq, p in board.piece_map().items():
        if p.piece_type == chess.KING:
            continue
        atacantes = list(board.attackers(not p.color, sq))
        if not atacantes:
            continue
        defensores = list(board.attackers(p.color, sq))
        menor_atacante = min(VALORES[board.piece_type_at(a)] or 100 for a in atacantes)
        pendurada = not defensores or menor_atacante < VALORES[p.piece_type]
        lista.append({
            **_peca(board, sq),
            "atacada_por": [_nome(board, a) for a in atacantes],
            "defendida_por": [_nome(board, d) for d in defensores],
            "indefesa": not defensores,
            "atacada_por_peca_de_menor_valor": menor_atacante < VALORES[p.piece_type],
            "pendurada": pendurada,
        })
    lista.sort(key=lambda x: (not x["pendurada"], -x["valor"]))
    return lista


def _sem_defesa(board: chess.Board) -> dict[str, list[str]]:
    """Peças (exceto rei e peões) que nenhuma peça da mesma cor defende."""
    out = {"white": [], "black": []}
    for sq, p in board.piece_map().items():
        if p.piece_type in (chess.KING, chess.PAWN):
            continue
        if not board.attackers(p.color, sq):
            out[COR[p.color]].append(_nome(board, sq))
    return out


_DIRECOES = {
    chess.BISHOP: [(1, 1), (1, -1), (-1, 1), (-1, -1)],
    chess.ROOK: [(1, 0), (-1, 0), (0, 1), (0, -1)],
}
_DIRECOES[chess.QUEEN] = _DIRECOES[chess.BISHOP] + _DIRECOES[chess.ROOK]


def _cravadas_e_espetos(board: chess.Board) -> tuple[list[dict], list[dict]]:
    """Percorre cada raio das peças de longo alcance e encontra alinhamentos
    peça da frente / peça de trás do mesmo lado."""
    cravadas, espetos = [], []
    for sq, p in board.piece_map().items():
        if p.piece_type not in _DIRECOES:
            continue
        for df, dr in _DIRECOES[p.piece_type]:
            f, r = chess.square_file(sq), chess.square_rank(sq)
            encontradas: list[chess.Square] = []
            while True:
                f, r = f + df, r + dr
                if not (0 <= f < 8 and 0 <= r < 8):
                    break
                alvo = chess.square(f, r)
                if board.piece_at(alvo):
                    encontradas.append(alvo)
                    if len(encontradas) == 2:
                        break
            if len(encontradas) < 2:
                continue
            frente, tras = encontradas
            pf, pt = board.piece_at(frente), board.piece_at(tras)
            if pf.color == p.color or pt.color == p.color:
                continue
            vf, vt = VALORES[pf.piece_type], VALORES[pt.piece_type]
            if pt.piece_type == chess.KING:
                vt = 100
            if pf.piece_type == chess.KING:
                vf = 100
            item = {
                "atacante": _nome(board, sq),
                "cor_atacante": COR[p.color],
                "peca_da_frente": _nome(board, frente),
                "peca_de_tras": _nome(board, tras),
            }
            if vt > vf:
                item["tipo"] = "absoluta" if pt.piece_type == chess.KING else "relativa"
                cravadas.append(item)
            elif vf > vt and pt.piece_type != chess.PAWN:
                espetos.append(item)
    return cravadas, espetos


def _xeques(board: chess.Board) -> list[str]:
    return [board.san(mv) for mv in board.legal_moves if board.gives_check(mv)][:LIMITE_LISTA]


def _mates_em_1(board: chess.Board) -> list[str]:
    out = []
    for mv in board.legal_moves:
        board.push(mv)
        mate = board.is_checkmate()
        board.pop()
        if mate:
            out.append(board.san(mv))
    return out


def _capturas(board: chess.Board) -> list[dict[str, Any]]:
    out = []
    for mv in board.legal_moves:
        if not board.is_capture(mv):
            continue
        if board.is_en_passant(mv):
            capturada = chess.PAWN
        else:
            capturada = board.piece_type_at(mv.to_square)
        defendida = bool(board.attackers(not board.turn, mv.to_square))
        out.append({"lance": board.san(mv), "captura": NOMES_PECAS[capturada],
                    "valor_capturado": VALORES[capturada],
                    "casa_defendida_pelo_adversario": defendida})
    out.sort(key=lambda x: -x["valor_capturado"])
    return out[:LIMITE_LISTA]


def _garfos(board: chess.Board) -> list[dict[str, Any]]:
    """Lances do lado que joga após os quais a peça movida ataca duas ou mais
    peças adversárias que valem mais que ela, ou estão indefesas, ou o rei."""
    out = []
    for mv in board.legal_moves:
        movida = board.piece_type_at(mv.from_square)
        board.push(mv)
        if board.is_checkmate():
            board.pop()
            continue
        valor_movida = VALORES[movida] if movida != chess.KING else 100
        alvos = []
        for alvo in board.attacks(mv.to_square):
            p = board.piece_at(alvo)
            # depois do push, board.turn é o adversário: só contam as peças dele
            if p is None or p.color != board.turn:
                continue
            valor = 100 if p.piece_type == chess.KING else VALORES[p.piece_type]
            indefesa = not board.attackers(p.color, alvo)
            if p.piece_type == chess.KING or valor > valor_movida or (indefesa and p.piece_type != chess.PAWN):
                alvos.append(_nome(board, alvo))
        board.pop()
        if len(alvos) >= 2:
            out.append({"lance": board.san(mv), "peca": NOMES_PECAS[movida], "ataca": alvos})
    return out[:LIMITE_LISTA]


def _rei(board: chess.Board, cor: chess.Color) -> dict[str, Any]:
    rei = board.king(cor)
    if rei is None:
        return {}
    f, r = chess.square_file(rei), chess.square_rank(rei)
    frente = 1 if cor == chess.WHITE else -1
    escudo = 0
    for df in (-1, 0, 1):
        for passos in (1, 2):
            ff, rr = f + df, r + frente * passos
            if 0 <= ff < 8 and 0 <= rr < 8:
                p = board.piece_at(chess.square(ff, rr))
                if p and p.piece_type == chess.PAWN and p.color == cor:
                    escudo += 1
                    break
    vizinhas = [s for s in chess.SquareSet(chess.BB_KING_ATTACKS[rei])]
    atacadas = [chess.square_name(s) for s in vizinhas if board.is_attacked_by(not cor, s)]
    colunas_abertas = []
    for df in (-1, 0, 1):
        ff = f + df
        if 0 <= ff < 8 and not (board.pieces(chess.PAWN, cor) & chess.BB_FILES[ff]):
            colunas_abertas.append(chess.FILE_NAMES[ff])
    return {
        "casa": chess.square_name(rei),
        "em_xeque": board.is_check() and board.turn == cor,
        "peoes_no_escudo": escudo,
        "casas_vizinhas_atacadas": atacadas,
        "colunas_sem_peao_proprio_perto": colunas_abertas,
        "pode_rocar": {
            "pequeno": board.has_kingside_castling_rights(cor),
            "grande": board.has_queenside_castling_rights(cor),
        },
        # Critério objetivo: escudo com no máximo 1 peão e 2+ casas vizinhas atacadas.
        "exposto": escudo <= 1 and len(atacadas) >= 2,
    }


def _fase(board: chess.Board) -> str:
    pesadas = sum(len(board.pieces(t, c)) * VALORES[t]
                  for t in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT)
                  for c in (chess.WHITE, chess.BLACK))
    if board.fullmove_number <= 10 and pesadas >= 56:
        return "abertura"
    if pesadas <= 26:
        return "final"
    return "meio-jogo"


def descrever_posicao(fen: str) -> dict[str, Any]:
    """Fatos objetivos da posição, calculados com python-chess."""
    board = _board(fen)
    cravadas, espetos = _cravadas_e_espetos(board)
    vez = board.turn
    return {
        "fen": board.fen(),
        "vez": COR[vez],
        "lance_numero": board.fullmove_number,
        "fase": _fase(board),
        "em_xeque": board.is_check(),
        "dando_xeque": [_nome(board, s) for s in board.checkers()],
        "xeque_mate": board.is_checkmate(),
        "afogado": board.is_stalemate(),
        "material": _material(board),
        "pecas_atacadas": _atacadas(board),
        "pecas_sem_defesa": _sem_defesa(board),
        "cravadas": cravadas,
        "espetos": espetos,
        "para_quem_joga": {
            "lances_legais": board.legal_moves.count(),
            "mate_em_1": _mates_em_1(board),
            "xeques_possiveis": _xeques(board),
            "capturas_possiveis": _capturas(board),
            "garfos_possiveis": _garfos(board),
        },
        "reis": {COR[c]: _rei(board, c) for c in (chess.WHITE, chess.BLACK)},
    }
