"""Seleção de jogadas do adversário com limites UCI exclusivos de `play`."""

from dataclasses import dataclass
from typing import Literal

import chess.engine

from mcp_server.tools.board import reproduzir_lances
from mcp_server.tools.engine import sessao_stockfish
from mcp_server.tools.pgn import LIMITE_MEIOS_LANCES

Dificuldade = Literal["iniciante", "intermediario", "avancado", "mestre"]


@dataclass(frozen=True)
class PerfilJogo:
    profundidade: int
    segundos: float
    skill: int
    elo: int | None = None


PERFIS = {
    "iniciante": PerfilJogo(4, 0.12, 0, 1350),
    "intermediario": PerfilJogo(8, 0.25, 6, 1600),
    "avancado": PerfilJogo(12, 0.50, 14, 2000),
    "mestre": PerfilJogo(18, 0.80, 20),
}


def opcoes_de_forca(opcoes, dificuldade: Dificuldade) -> dict:
    perfil = PERFIS[dificuldade]
    skill = opcoes.get("Skill Level")
    elo = opcoes.get("UCI_Elo")
    limitar = opcoes.get("UCI_LimitStrength")
    skill_disponivel = skill and skill.type == "spin"
    elo_disponivel = limitar and limitar.type == "check" and elo and elo.type == "spin"

    def limitar_intervalo(opcao, alvo: int) -> int:
        minimo = opcao.min if opcao.min is not None else alvo
        maximo = opcao.max if opcao.max is not None else alvo
        return max(minimo, min(maximo, alvo))

    if perfil.elo is not None and elo_disponivel and (dificuldade != "iniciante" or not skill_disponivel):
        return {"UCI_Elo": limitar_intervalo(elo, perfil.elo), "UCI_LimitStrength": True}

    resultado = {"UCI_LimitStrength": False} if limitar and limitar.type == "check" else {}
    if skill_disponivel:
        resultado["Skill Level"] = limitar_intervalo(skill, perfil.skill)
    return resultado


def jogar_stockfish(fen_inicial: str, lances: list[str], dificuldade: Dificuldade) -> dict:
    """Calcula um lance legal com o histórico e o perfil de jogo indicados."""
    if len(lances) >= LIMITE_MEIOS_LANCES:
        raise ValueError("O jogo atingiu o limite de meios-lances.")
    tabuleiro = reproduzir_lances(fen_inicial, lances)
    if tabuleiro.is_game_over():
        raise ValueError("A partida já terminou pelas regras do xadrez.")
    perfil = PERFIS[dificuldade]
    with sessao_stockfish() as motor:
        opcoes = opcoes_de_forca(motor.options, dificuldade)
        resposta = motor.play(tabuleiro, chess.engine.Limit(depth=perfil.profundidade, time=perfil.segundos),
                              game=object(), options=opcoes)
        if resposta.move is None or resposta.move not in tabuleiro.legal_moves:
            raise RuntimeError("O Stockfish não devolveu um lance legal.")
        return {"uci": resposta.move.uci(), "opcoes_uci": opcoes, "motor": motor.id["name"]}
