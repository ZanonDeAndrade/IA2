"""Conversão entre SAN em inglês (Nf3) e SAN em português (Cf3).

Peças: K/R = rei, Q/D = dama, R/T = torre, B/B = bispo, N/C = cavalo.
Como "R" significa rei em português e torre em inglês, a leitura de um lance
escrito pelo LLM tenta as duas notações (ver `interpretar_lance`).
"""

from __future__ import annotations

import re

import chess

EN_PARA_PT = {"K": "R", "Q": "D", "R": "T", "N": "C", "B": "B"}
PT_PARA_EN = {"R": "K", "D": "Q", "T": "R", "C": "N", "B": "B"}

NOMES_PECAS = {
    chess.PAWN: "peão", chess.KNIGHT: "cavalo", chess.BISHOP: "bispo",
    chess.ROOK: "torre", chess.QUEEN: "dama", chess.KING: "rei",
}
VALORES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}

_UCI = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")
_PREFIXO_NUMERO = re.compile(r"^\d+\s*\.(\.\.)?\s*")
_SUFIXOS = re.compile(r"[!?+#]+$")


def _trocar_pecas(san: str, mapa: dict[str, str]) -> str:
    if not san:
        return san
    if san[0] in mapa:
        san = mapa[san[0]] + san[1:]
    return re.sub(r"=([A-Z])", lambda m: "=" + mapa.get(m.group(1), m.group(1)), san)


def san_pt(san: str) -> str:
    """Nf3 -> Cf3, Qxd7+ -> Dxd7+, e8=Q -> e8=D."""
    return _trocar_pecas(san, EN_PARA_PT)


def san_en(san: str) -> str:
    """Cf3 -> Nf3, Dxd7+ -> Qxd7+, Rg1 -> Kg1 (lê como português)."""
    return _trocar_pecas(san, PT_PARA_EN)


def limpar(lance: str) -> str:
    """Remove número do lance (12. / 12...), anotações (!?) e normaliza roque."""
    s = lance.strip()
    s = _PREFIXO_NUMERO.sub("", s)
    s = _SUFIXOS.sub("", s)
    s = s.replace("0-0-0", "O-O-O").replace("0-0", "O-O")
    return s


def interpretar_lance(board: chess.Board, lance: str, preferir: str = "en"
                      ) -> tuple[chess.Move | None, str | None, bool]:
    """Tenta ler `lance` como UCI, SAN inglês ou SAN português.

    Devolve (lance, notação, ambíguo). `ambíguo` é True quando o texto é legal
    nas duas notações com significados diferentes (ex.: "Rd2" = torre ou rei);
    nesse caso vence a notação de `preferir` ("en" ou "pt").
    """
    s = limpar(lance)
    if not s:
        return None, None, False

    if _UCI.match(s):
        try:
            mv = chess.Move.from_uci(s)
            if mv in board.legal_moves:
                return mv, "uci", False
        except ValueError:
            pass

    candidatos: list[tuple[chess.Move, str]] = []
    ordem = [("san", s), ("san_pt", san_en(s))]
    if preferir == "pt":
        ordem.reverse()
    for notacao, texto in ordem:
        try:
            mv = board.parse_san(texto)
            if all(mv != c[0] for c in candidatos):
                candidatos.append((mv, notacao))
        except ValueError:
            continue

    if not candidatos:
        return None, None, False
    mv, notacao = candidatos[0]
    return mv, notacao, len(candidatos) > 1
