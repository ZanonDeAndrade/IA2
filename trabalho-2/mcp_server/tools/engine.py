"""Ferramentas do motor: avaliação de posições e partidas com o Stockfish.

O binário é acionado pelo ``python-chess`` via UCI (caminho em ``STOCKFISH_PATH``
ou ``stockfish`` no PATH). Uma única instância do motor é aberta na primeira
chamada e reaproveitada por todas as ferramentas, com um lock (o protocolo UCI é
sequencial) e limite de tempo por posição.
"""

from __future__ import annotations

import atexit
import io
import os
import shutil
import threading
from dataclasses import dataclass
from typing import Any, Callable

import chess
import chess.engine
import chess.pgn

from mcp_server.tools.classificacao import chance_da_avaliacao, classificar
from mcp_server.tools.notacao import san_pt

# Valor em centipeões usado para representar mate (gráficos e médias).
CP_MATE = 10_000

CORES = {chess.WHITE: "white", chess.BLACK: "black"}


class ErroMotor(RuntimeError):
    """Stockfish ausente ou travado."""


def _caminho_stockfish() -> str:
    caminho = os.getenv("STOCKFISH_PATH") or shutil.which("stockfish")
    if not caminho or not (os.path.isfile(caminho) or shutil.which(caminho)):
        raise ErroMotor(
            "Stockfish não encontrado. Instale (brew install stockfish / apt install stockfish) "
            "ou defina STOCKFISH_PATH no .env."
        )
    return caminho


class Motor:
    """Instância única e reaproveitada do Stockfish."""

    def __init__(self) -> None:
        self._engine: chess.engine.SimpleEngine | None = None
        self._lock = threading.Lock()

    def _abrir(self) -> chess.engine.SimpleEngine:
        if self._engine is None:
            engine = chess.engine.SimpleEngine.popen_uci(_caminho_stockfish())
            opcoes = {
                "Threads": int(os.getenv("STOCKFISH_THREADS", "2")),
                "Hash": int(os.getenv("STOCKFISH_HASH_MB", "128")),
            }
            engine.configure({k: v for k, v in opcoes.items() if k in engine.options})
            self._engine = engine
        return self._engine

    def analisar(self, board: chess.Board, limite: chess.engine.Limit, multipv: int = 1
                 ) -> list[chess.engine.InfoDict]:
        with self._lock:
            for tentativa in range(2):
                try:
                    infos = self._abrir().analyse(board, limite, multipv=multipv)
                    return infos if isinstance(infos, list) else [infos]
                except (chess.engine.EngineTerminatedError, chess.engine.EngineError, BrokenPipeError):
                    # Motor morreu: descarta e tenta abrir de novo uma vez.
                    self._fechar_sem_lock()
                    if tentativa == 1:
                        raise ErroMotor("O Stockfish parou de responder.")
        raise ErroMotor("O Stockfish parou de responder.")  # pragma: no cover

    def _fechar_sem_lock(self) -> None:
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:
                pass
            self._engine = None

    def fechar(self) -> None:
        with self._lock:
            self._fechar_sem_lock()


motor = Motor()
# O SimpleEngine roda numa thread que não é daemon; o interpretador espera essa
# thread antes dos handlers do atexit. `_register_atexit` roda antes da espera
# (é o mesmo gancho usado por concurrent.futures).
_registrar_saida = getattr(threading, "_register_atexit", atexit.register)
_registrar_saida(motor.fechar)


# --------------------------------------------------------------------------- #
# Avaliações
# --------------------------------------------------------------------------- #

@dataclass
class Avaliacao:
    """Avaliação do ponto de vista das brancas (uso interno)."""
    cp: int          # centipeões; ±CP_MATE quando há mate
    mate: int | None  # lances até o mate (positivo = brancas dão mate)

    def para(self, cor: chess.Color) -> dict[str, Any]:
        """Avaliação do ponto de vista de `cor`: {"cp", "mate"}."""
        sinal = 1 if cor == chess.WHITE else -1
        return {"cp": self.cp * sinal, "mate": None if self.mate is None else self.mate * sinal}

    def chance(self, cor: chess.Color) -> float:
        a = self.para(cor)
        return chance_da_avaliacao(a["cp"], a["mate"])


def _de_score(score: chess.engine.PovScore) -> Avaliacao:
    branco = score.white()
    mate = branco.mate()
    if mate is not None:
        # Mate(0) (posição já é mate) não chega aqui: _final() trata antes.
        return Avaliacao(CP_MATE if mate > 0 else -CP_MATE, mate)
    return Avaliacao(branco.score(), None)


def _final(board: chess.Board) -> Avaliacao | None:
    """Avaliação de posições terminais (o motor não analisa posição sem lances)."""
    if board.is_checkmate():
        # Quem está na vez levou mate: o jogo acabou, então vale ±CP_MATE (100% / 0%).
        return Avaliacao(-CP_MATE if board.turn == chess.WHITE else CP_MATE, None)
    if board.is_game_over(claim_draw=False):
        return Avaliacao(0, None)
    return None


def _linha_san(board: chess.Board, pv: list[chess.Move], max_lances: int = 8) -> list[str]:
    b = board.copy(stack=False)
    linha = []
    for mv in pv[:max_lances]:
        if mv not in b.legal_moves:
            break
        linha.append(b.san(mv))
        b.push(mv)
    return linha


def _board(fen: str) -> chess.Board:
    try:
        board = chess.Board(fen)
    except ValueError as e:
        raise ValueError(f"FEN inválido: {e}") from None
    if not board.is_valid():
        raise ValueError(f"Posição ilegal no FEN: {board.status()!r}")
    return board


# --------------------------------------------------------------------------- #
# analisar_posicao
# --------------------------------------------------------------------------- #

def analisar_posicao(fen: str, profundidade: int = 18, multipv: int = 3) -> dict:
    """Avalia uma posição com o Stockfish.

    Returns:
        dict com:
            - ``avaliacao``: ``{"cp", "mate"}`` do ponto de vista do lado a jogar
              (``mate`` positivo = o lado a jogar dá mate);
            - ``avaliacao_brancas``: a mesma avaliação do ponto de vista das brancas;
            - ``melhores_lances``: os ``multipv`` melhores lances, cada um com
              ``san``, ``san_pt``, ``uci``, ``avaliacao`` e ``linha`` (SAN);
            - ``linha_principal``: sequência de lances (SAN) da variante principal.
    """
    board = _board(fen)
    profundidade = max(1, min(int(profundidade), 30))
    multipv = max(1, min(int(multipv), 5))
    tempo_max = float(os.getenv("TEMPO_MAX_POSICAO", "1.5"))
    vez = board.turn

    base = {"fen": board.fen(), "vez": CORES[vez]}
    final = _final(board)
    if final is not None:
        return {**base, "avaliacao": final.para(vez), "avaliacao_brancas": final.para(chess.WHITE),
                "fim_de_jogo": True, "melhores_lances": [], "linha_principal": [], "profundidade": 0}

    infos = motor.analisar(board, chess.engine.Limit(depth=profundidade, time=tempo_max), multipv)
    lances = []
    for info in infos:
        pv = info.get("pv") or []
        if not pv:
            continue
        san = board.san(pv[0])
        lances.append({
            "san": san,
            "san_pt": san_pt(san),
            "uci": pv[0].uci(),
            "avaliacao": _de_score(info["score"]).para(vez),
            "linha": _linha_san(board, pv),
        })
    if not lances:
        raise ErroMotor("O motor não devolveu nenhum lance.")

    principal = _de_score(infos[0]["score"])
    return {
        **base,
        "avaliacao": principal.para(vez),
        "avaliacao_brancas": principal.para(chess.WHITE),
        "fim_de_jogo": False,
        "melhores_lances": lances,
        "linha_principal": lances[0]["linha"],
        "profundidade": infos[0].get("depth", 0),
    }


# --------------------------------------------------------------------------- #
# analisar_partida
# --------------------------------------------------------------------------- #

def ler_pgn(pgn: str) -> chess.pgn.Game:
    jogo = chess.pgn.read_game(io.StringIO(pgn or ""))
    if jogo is None:
        raise ValueError("PGN inválido: nenhuma partida encontrada.")
    if jogo.errors:
        raise ValueError(f"PGN inválido: {jogo.errors[0]}")
    if not any(True for _ in jogo.mainline_moves()):
        raise ValueError("PGN inválido: a partida não tem lances.")
    return jogo


def ler_cor(cor_do_jogador: str | None) -> chess.Color | None:
    """'white'/'black' (ou brancas/pretas). None/'both'/'ambas' = os dois lados."""
    if cor_do_jogador is None:
        return None
    c = cor_do_jogador.strip().lower()
    if c in {"white", "w", "brancas", "branco", "brancos"}:
        return chess.WHITE
    if c in {"black", "b", "pretas", "preto", "pretos", "negras"}:
        return chess.BLACK
    if c in {"both", "ambas", "ambos", ""}:
        return None
    raise ValueError("cor_do_jogador deve ser 'white' ou 'black'.")


@dataclass
class _Posicao:
    avaliacao: Avaliacao
    melhor: chess.Move | None
    linha: list[chess.Move]


def analisar_partida(pgn: str, cor_do_jogador: str,
                     progresso: Callable[[int, int], None] | None = None) -> list[dict]:
    """Analisa todos os lances de uma partida e classifica os do jogador.

    Cada posição é avaliada uma só vez (a avaliação "depois" de um lance é a
    "antes" do lance seguinte), com profundidade ``PROFUNDIDADE_PARTIDA`` e no
    máximo ``TEMPO_POR_LANCE`` segundos por posição.

    Returns:
        Lista com um dict por meio-lance, na ordem da partida. Os campos
        ``cp_*``, ``mate_*`` e ``chance_vitoria_*`` são do ponto de vista do
        jogador (``cor_do_jogador``); ``queda`` é do ponto de vista de quem jogou.
        ``classe`` (``aceitavel``, ``imprecisao``, ``erro``, ``erro_grave``) só é
        preenchida nos lances do jogador (``do_jogador = True``).
    """
    jogo = ler_pgn(pgn)
    cor = ler_cor(cor_do_jogador)
    limite = chess.engine.Limit(depth=int(os.getenv("PROFUNDIDADE_PARTIDA", "14")),
                                time=float(os.getenv("TEMPO_POR_LANCE", "0.4")))

    board = jogo.board()
    lances = list(jogo.mainline_moves())
    total = len(lances) + 1

    posicoes: list[_Posicao] = []
    tabuleiros: list[chess.Board] = []
    for i in range(total):
        tabuleiros.append(board.copy(stack=False))
        final = _final(board)
        if final is not None:
            posicoes.append(_Posicao(final, None, []))
        else:
            info = motor.analisar(board, limite, 1)[0]
            pv = info.get("pv") or []
            posicoes.append(_Posicao(_de_score(info["score"]), pv[0] if pv else None, pv))
        if progresso:
            progresso(i + 1, total)
        if i < len(lances):
            board.push(lances[i])

    resultado = []
    for i, mv in enumerate(lances):
        antes, depois = posicoes[i], posicoes[i + 1]
        b_antes = tabuleiros[i]
        quem = b_antes.turn
        ponto_de_vista = quem if cor is None else cor
        do_jogador = cor is None or quem == cor

        era_o_melhor = antes.melhor == mv
        queda = 0.0 if era_o_melhor else max(
            0.0, round(antes.avaliacao.chance(quem) - depois.avaliacao.chance(quem), 2))
        melhor_san = b_antes.san(antes.melhor) if antes.melhor else None
        av_antes, av_depois = antes.avaliacao.para(ponto_de_vista), depois.avaliacao.para(ponto_de_vista)
        san = b_antes.san(mv)

        resultado.append({
            "indice": i + 1,                       # meio-lance (1 = primeiro lance das brancas)
            "numero": b_antes.fullmove_number,
            "cor": CORES[quem],
            "san": san,
            "san_pt": san_pt(san),
            "uci": mv.uci(),
            "fen_antes": b_antes.fen(),
            "fen_depois": tabuleiros[i + 1].fen(),
            "cp_antes": av_antes["cp"],
            "cp_depois": av_depois["cp"],
            "mate_antes": av_antes["mate"],
            "mate_depois": av_depois["mate"],
            "chance_vitoria_antes": antes.avaliacao.chance(ponto_de_vista),
            "chance_vitoria_depois": depois.avaliacao.chance(ponto_de_vista),
            "queda": queda,
            "classe": classificar(queda) if do_jogador else None,
            "do_jogador": do_jogador,
            "era_o_melhor": era_o_melhor,
            "melhor_lance": melhor_san,
            "melhor_lance_pt": san_pt(melhor_san) if melhor_san else None,
            "melhor_lance_uci": antes.melhor.uci() if antes.melhor else None,
            "linha_motor": _linha_san(b_antes, antes.linha),
        })
    return resultado
