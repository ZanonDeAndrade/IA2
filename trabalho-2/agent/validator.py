"""Confere a legalidade e a origem das variantes citadas pelo treinador."""

import asyncio
from collections.abc import Awaitable, Callable
import re
from typing import NotRequired, TypedDict

import chess

ValidadorMCP = Callable[[str, list[str]], Awaitable[list[dict]]]
_LANCE = re.compile(
    r"(?<!\w)(?:[O0]-[O0](?:-[O0])?"
    r"|[KQRBNKDTFC][a-z]?[0-9]?[x×\-]?[a-z][0-9]+(?:=?[QRBNDTFC])?"
    r"|[a-h][0-9]+[-x]?[a-z][0-9]+[qrbnQRBN]?"
    r"|[a-h](?:[x×][a-z])?[0-9]+(?:=?[QRBNqrbnDTFC])?)[+#]?(?!\w)"
)
_MESMA_VARIANTE = re.compile(r"(?:\s|`|\*|!|\?|,|\d+\.{1,3}|→|->)+")


class ResultadoValidacao(TypedDict):
    valida: bool
    lances: list[dict]
    erros: list[str]
    ferramenta_indisponivel: NotRequired[bool]


def ler_fen(fen: str) -> chess.Board:
    if len(fen.split()) != 6:
        raise ValueError("Informe um FEN completo.")
    tabuleiro = chess.Board(fen)
    if not tabuleiro.is_valid():
        raise ValueError("Posição FEN inválida.")
    return tabuleiro


def extrair_lances(texto: str) -> list[str]:
    return [match.group() for match in _LANCE.finditer(texto)]


def agrupar_variantes(texto: str) -> list[list[str]]:
    """Agrupa citações consecutivas para validar cada variante desde o seu início."""
    grupos: list[list[str]] = []
    fim = 0
    for match in _LANCE.finditer(texto):
        if grupos and _MESMA_VARIANTE.fullmatch(texto[fim:match.start()]):
            grupos[-1].append(match.group())
        else:
            grupos.append([match.group()])
        fim = match.end()
    return grupos


def _movimento(tabuleiro: chess.Board, lance: str) -> chess.Move:
    movimento = tabuleiro.parse_san(lance.replace("×", "x"))
    if movimento not in tabuleiro.legal_moves:
        raise ValueError("Lance ilegal.")
    san = tabuleiro.san(movimento)
    if lance.endswith(("+", "#")) and lance[-1] != san[-1]:
        raise ValueError("Marcação de xeque ou mate incorreta.")
    return movimento


def _normalizar(tabuleiro: chess.Board, linha: list[str]) -> list[str]:
    copia = tabuleiro.copy(stack=False)
    resultado = []
    for lance in linha:
        movimento = _movimento(copia, lance)
        resultado.append(copia.san(movimento))
        copia.push(movimento)
    return resultado


async def validar_resposta_async(
    texto: str,
    fen: str,
    linha_motor: list[str] | None = None,
    *,
    validar_lances: ValidadorMCP,
    outras_linhas: tuple[list[str], ...] = (),
) -> ResultadoValidacao:
    """Valida variantes iniciadas no FEN e exige um prefixo confirmado para cada uma."""
    saida: ResultadoValidacao = {"valida": False, "lances": [], "erros": []}
    if not texto.strip():
        saida["erros"].append("Resposta vazia.")
        return saida
    try:
        inicial = ler_fen(fen)
        referencias = [_normalizar(inicial, linha) for linha in (linha_motor or [], *outras_linhas) if linha]
    except (ValueError, TypeError, AttributeError):
        saida["erros"].append("FEN ou variante de referência inválida.")
        return saida

    for grupo in agrupar_variantes(texto):
        tabuleiro = inicial.copy(stack=False)
        normalizados = []
        for lance in grupo:
            try:
                registros = await validar_lances(tabuleiro.fen(), [lance])
            except Exception:
                saida["erros"].append("Ferramenta de validação indisponível.")
                saida["ferramenta_indisponivel"] = True
                return saida
            try:
                movimento = _movimento(tabuleiro, lance)
                san = tabuleiro.san(movimento)
                if (
                    not isinstance(registros, list) or len(registros) != 1
                    or not isinstance(registros[0], dict)
                    or registros[0].get("lance") != lance
                    or registros[0].get("legal") is not True or registros[0].get("san") != san
                ):
                    raise ValueError("MCP não confirmou o lance.")
            except ValueError:
                saida["lances"].append({"lance": lance, "legal": False})
                saida["erros"].append(f"Lance ilegal ou não confirmado na variante: {lance}.")
                break
            saida["lances"].append({"lance": lance, "legal": True, "san": san, "fen": tabuleiro.fen()})
            normalizados.append(san)
            tabuleiro.push(movimento)
        else:
            if not any(linha[:len(normalizados)] == normalizados for linha in referencias):
                saida["erros"].append(f"Variante sem suporte do Stockfish: {' '.join(grupo)}.")
    saida["valida"] = not saida["erros"]
    return saida


def validar_resposta(texto: str, fen: str, linha_motor: list[str] | None = None) -> ResultadoValidacao:
    """Entrada síncrona que usa a mesma implementação de ferramenta do servidor MCP."""
    from mcp_server.tools.board import validar_lances

    async def chamar(posicao: str, lances: list[str]) -> list[dict]:
        return validar_lances(posicao, lances)

    return asyncio.run(validar_resposta_async(texto, fen, linha_motor, validar_lances=chamar))


def explicacao_padrao(lance_jogado: str, melhor_lance: str, linha_motor: list[str]) -> str:
    """Formata dados previamente confirmados. O grafo valida o texto antes de retorná-lo."""
    texto = f"O lance jogado foi `{lance_jogado}`. O Stockfish indicou `{melhor_lance}` como alternativa."
    if len(linha_motor) > 1:
        texto += f" A variante do motor segue com `{' '.join(linha_motor)}`."
    return texto
