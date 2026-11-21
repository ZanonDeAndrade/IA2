"""Leitura compartilhada de PGN padrão e metadados da partida."""

from io import StringIO
import re

import chess
import chess.pgn

LIMITE_PGN = 256_000
LIMITE_MEIOS_LANCES = 600
USUARIO = re.compile(r"[a-zA-Z0-9_-]{1,50}")
_ANOTACOES = re.compile(r'^[ \t]*\[[^\r\n]*"\][ \t]*$|\{[^}]*\}|;[^\n]*|^%[^\n]*', re.MULTILINE)


class LeitorPGN(chess.pgn.GameBuilder):
    def handle_error(self, error):
        self.game.errors.append(error)


def ler_partida(pgn: str) -> chess.pgn.Game:
    if not pgn.strip() or len(pgn) > LIMITE_PGN:
        raise ValueError("Informe um PGN de até 256 mil caracteres.")
    texto = pgn.lstrip("\ufeff")
    movetext = _ANOTACOES.sub(" ", texto)
    resto = chess.pgn.MOVETEXT_REGEX.sub(" ", movetext)
    resto = re.sub(r"\d+\.{1,3}|\be\.p\.", " ", resto)
    if any(c in movetext for c in "{}") or resto.strip(" \t\r\n+#"):
        raise ValueError("O PGN contém notação inválida.")
    fonte = StringIO(texto)
    jogo = chess.pgn.read_game(fonte, Visitor=LeitorPGN)
    if (jogo is None or jogo.errors or jogo.headers.get("Variant", "Standard") != "Standard"
            or jogo.headers["Result"] not in {"1-0", "0-1", "1/2-1/2", "*"}):
        raise ValueError("PGN inválido ou de uma variante não suportada.")
    tabuleiro = jogo.board()
    lances = list(jogo.mainline_moves())
    if not tabuleiro.is_valid() or not 0 < len(lances) <= LIMITE_MEIOS_LANCES:
        raise ValueError("O PGN precisa ter posição válida e de 1 a 600 meios-lances.")
    for lance in lances:
        if not tabuleiro.is_legal(lance):
            raise ValueError("O PGN contém um lance ilegal.")
        tabuleiro.push(lance)
    if fonte.read().strip():
        raise ValueError("Envie apenas uma partida por PGN.")
    return jogo


def metadados(jogo: chess.pgn.Game, pgn: str, usuario: str | None = None, cor: str | None = None) -> dict:
    h = jogo.headers
    jogadores = {}
    for lado in ("white", "black"):
        tag = lado.capitalize()
        rating = h.get(tag + "Elo", "")
        jogadores[lado] = {
            "nome": h[tag] if h[tag] != "?" else None,
            "rating": int(rating) if re.fullmatch(r"[0-9]{1,4}", rating) else None,
        }
    if cor is None:
        cor = next((lado for lado, dados in jogadores.items() if usuario and
                    (dados["nome"] or "").casefold() == usuario.casefold()), "white")
    adversario = "black" if cor == "white" else "white"
    total = sum(1 for _ in jogo.mainline_moves())
    data = h.get("UTCDate", h.get("Date", "")).replace(".", "-")
    return {
        "pgn": pgn, "usuario": usuario or jogadores[cor]["nome"], "cor_do_jogador": cor,
        "jogadores": jogadores, "adversario": jogadores[adversario]["nome"], "resultado": h["Result"],
        "abertura": h.get("Opening") or h.get("ECO"), "eco": h.get("ECO"),
        "data": data if re.fullmatch(r"\d{4}-\d{2}-\d{2}", data) else None,
        "url": None, "ritmo": None, "fen_inicial": jogo.board().fen(), "total_lances": total,
    }
