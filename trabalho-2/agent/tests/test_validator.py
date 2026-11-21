import asyncio

import chess
import pytest

from agent.validator import explicacao_padrao, extrair_lances, validar_resposta, validar_resposta_async
from mcp_server.tools.board import validar_lances

FEN = chess.STARTING_FEN
LINHA = ["e4", "e5", "Nf3"]


@pytest.mark.parametrize(("texto", "valida"), [
    ("O motor indica `e4`.", True),
    ("Siga 1.e4 e5 2.Nf3.", True),
    ("O motor indica e2e4.", True),
    ("O motor indica e4+.", False),
    ("O motor indica e5.", False),
    ("O motor indica Qz9.", False),
    ("O motor indica d4.", False),
    ("Siga e4 d5.", False),
    ("A prioridade é proteger o rei.", True),
    ("", False),
])
def test_validacao(texto, valida):
    assert validar_resposta(texto, FEN, LINHA)["valida"] is valida


def test_lance_legal_sem_respaldo():
    assert not validar_resposta("Melhor lance: e4.", FEN)["valida"]
    assert extrair_lances("Siga 1.e4, e5 e depois Nf3.") == LINHA


def test_validacao_avanca_o_fen_a_cada_meio_lance():
    estados = []

    async def ferramenta(fen, lances):
        estados.append(fen)
        return validar_lances(fen, lances)

    resultado = asyncio.run(validar_resposta_async("1.e4 e5 2.Nf3", FEN, LINHA, validar_lances=ferramenta))
    assert resultado["valida"]
    tabuleiro = chess.Board()
    for fen, lance in zip(estados, LINHA, strict=True):
        assert fen == tabuleiro.fen()
        tabuleiro.push_san(lance)


def test_fallback_so_cita_dados_confirmados():
    async def ferramenta(fen, lances):
        return validar_lances(fen, lances)

    texto = explicacao_padrao("d4", "e4", LINHA)
    assert extrair_lances(texto) == ["d4", "e4", *LINHA]
    assert asyncio.run(validar_resposta_async(
        texto, FEN, LINHA, validar_lances=ferramenta, outras_linhas=(["d4"],),
    ))["valida"]


def test_ferramenta_preserva_validacao_independente_e_rejeita_lance_nulo():
    assert [item["legal"] for item in validar_lances(FEN, ["e4", "d2d4", "e5", "0000"])] == [
        True, True, False, False,
    ]
