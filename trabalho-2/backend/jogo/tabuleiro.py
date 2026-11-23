"""Regras de encerramento e exportação de partidas jogadas."""

import chess
import chess.pgn

from backend.jogo.modelos import EmpateDisponivel, EmpateReivindicado, JogoSalvo
from mcp_server.tools.pgn import LIMITE_MEIOS_LANCES, metadados

_ENCERRAMENTOS = {
    chess.Termination.CHECKMATE: "xeque_mate",
    chess.Termination.STALEMATE: "afogamento",
    chess.Termination.INSUFFICIENT_MATERIAL: "material_insuficiente",
    chess.Termination.FIVEFOLD_REPETITION: "repeticao_quintupla",
    chess.Termination.SEVENTYFIVE_MOVES: "regra_75_lances",
}
_ANOTACOES = {
    "imprecisao": chess.pgn.NAG_DUBIOUS_MOVE, "erro": chess.pgn.NAG_MISTAKE,
    "erro_grave": chess.pgn.NAG_BLUNDER,
}


def motivo_empate(tabuleiro: chess.Board) -> EmpateReivindicado | None:
    if tabuleiro.is_fifty_moves():
        return "regra_50_lances"
    if tabuleiro.is_repetition(3):
        return "tripla_repeticao"
    return None


def empate_disponivel(tabuleiro: chess.Board) -> EmpateDisponivel:
    if motivo := motivo_empate(tabuleiro):
        return EmpateDisponivel(agora=motivo)
    if not (tabuleiro.can_claim_fifty_moves() or tabuleiro.can_claim_threefold_repetition()):
        return EmpateDisponivel()
    lances = {}
    for lance in list(tabuleiro.legal_moves):
        tabuleiro.push(lance)
        try:
            if motivo := motivo_empate(tabuleiro):
                lances[lance.uci()] = motivo
        finally:
            tabuleiro.pop()
    return EmpateDisponivel(por_lance=lances)


def verificar_fim(jogo: JogoSalvo, tabuleiro: chess.Board) -> None:
    if resultado := tabuleiro.outcome(claim_draw=False):
        jogo.status = "encerrada"
        jogo.resultado = resultado.result()
        jogo.motivo = _ENCERRAMENTOS[resultado.termination]
    elif len(jogo.lances) >= LIMITE_MEIOS_LANCES:
        jogo.status = "encerrada"
        jogo.motivo = "limite_de_lances"


def exportar(jogo: JogoSalvo, tabuleiro: chess.Board) -> chess.pgn.Game:
    partida = chess.pgn.Game.from_board(tabuleiro)
    branca = jogo.cor_do_jogador == "white"
    partida.headers.update({
        "Event": "Lance a Lance - Treino contra Stockfish",
        "Date": jogo.criado_em[:10].replace("-", "."),
        "White": "Jogador" if branca else "Stockfish",
        "Black": "Stockfish" if branca else "Jogador",
        "Result": jogo.resultado,
    })
    if jogo.motivo:
        partida.headers["LanceMotivo"] = jogo.motivo
    for no, lance in zip(partida.mainline(), jogo.lances):
        if dados := lance.avaliacao:
            if nag := _ANOTACOES.get(dados.classe):
                no.nags.add(nag)
            no.comment = f"Classe: {dados.classe}. Melhor alternativa: {dados.melhor_lance}."
    jogo.pgn = partida.accept(chess.pgn.StringExporter(headers=True, variations=False, comments=True))
    return partida


def preparar_revisao(jogo: JogoSalvo, partida: chess.pgn.Game) -> dict | None:
    if jogo.status != "encerrada" or not jogo.lances or jogo.partida_analise_id:
        return None
    dados = metadados(partida, jogo.pgn, cor=jogo.cor_do_jogador)
    # Cada treino é recuperável separadamente, inclusive duas partidas idênticas.
    return {**dados, "chave_pgn": ["jogo", jogo.id], "usuario": jogo.usuario}
