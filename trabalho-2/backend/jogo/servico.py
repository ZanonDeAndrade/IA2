"""Orquestra um turno completo e a avaliação pedagógica dos lances."""

import asyncio
from contextlib import asynccontextmanager
from secrets import choice
from time import perf_counter
from uuid import uuid4

import chess
from fastapi import HTTPException

from backend import db, services
from backend.jogo import repositorio, tabuleiro as regras
from backend.jogo.modelos import (
    AvaliacaoPosicao, Configuracoes, EmpateDisponivel, EstadoJogo, IniciarJogo, JogoSalvo, LanceJogo,
    SelecaoMotor,
)
from backend.schemas import Movimento
from mcp_server.tools.board import reproduzir_lances
from mcp_server.tools.engine import normalizar_avaliacao, perfil_analise


@asynccontextmanager
async def prazo_motor():
    try:
        async with asyncio.timeout(repositorio.PRAZO_MOTOR):
            yield
    except TimeoutError as erro:
        raise HTTPException(504, "O Stockfish excedeu o prazo do turno. Atualize a partida e tente novamente.") from erro


def reproduzir(jogo: JogoSalvo) -> chess.Board:
    return reproduzir_lances(jogo.fen_inicial, [lance.uci for lance in jogo.lances])


def estado(jogo: JogoSalvo, processando: bool = False) -> EstadoJogo:
    tabuleiro = reproduzir(jogo)
    andamento = jogo.status == "em_andamento"
    cor = chess.COLOR_NAMES[tabuleiro.turn]
    vez = ("jogador" if cor == jogo.cor_do_jogador else "ia") if andamento else None
    disponivel = vez == "jogador" and not processando
    return EstadoJogo(
        **jogo.model_dump(), cor_da_ia="black" if jogo.cor_do_jogador == "white" else "white",
        vez=vez, cor_da_vez=cor if andamento else None, em_xeque=tabuleiro.is_check(),
        processando=processando, lances_legais=[m.uci() for m in tabuleiro.legal_moves] if disponivel else [],
        empate_reivindicavel=regras.empate_disponivel(tabuleiro) if disponivel else EmpateDisponivel(),
        estatisticas=estatisticas(jogo),
    )


def estatisticas(jogo: JogoSalvo) -> dict:
    return services.resumo({"cor_do_jogador": jogo.cor_do_jogador,
                            "lances": [l.avaliacao.model_dump() for l in jogo.lances if l.avaliacao]})


def validar_vez(jogo: JogoSalvo, tabuleiro: chess.Board) -> None:
    if jogo.status != "em_andamento":
        raise HTTPException(409, "A partida já foi encerrada.")
    if chess.COLOR_NAMES[tabuleiro.turn] != jogo.cor_do_jogador:
        raise HTTPException(409, "Aguarde a jogada do Stockfish.")


def lance_legal(tabuleiro: chess.Board, uci: str) -> chess.Move:
    try:
        lance = tabuleiro.parse_uci(uci)
        if lance.uci() != uci or not tabuleiro.is_legal(lance):
            raise ValueError
        return lance
    except ValueError as erro:
        raise HTTPException(422, "Lance ilegal na posição atual. Confira também a peça da promoção.") from erro


def aplicar(jogo: JogoSalvo, tabuleiro: chess.Board, lance: chess.Move,
            selecao: SelecaoMotor | None = None) -> LanceJogo:
    indice = len(jogo.lances) + 1
    dados = {"id": f"{jogo.id}:{indice}", "indice": indice, "numero": tabuleiro.fullmove_number,
             "cor": chess.COLOR_NAMES[tabuleiro.turn], "autor": "ia" if selecao else "jogador",
             "san": tabuleiro.san(lance), "uci": lance.uci(), "fen_antes": tabuleiro.fen()}
    tabuleiro.push(lance)
    jogo.fen = tabuleiro.fen()
    registro = LanceJogo(**dados, fen_depois=jogo.fen, selecao_motor=selecao)
    jogo.lances.append(registro)
    regras.verificar_fim(jogo, tabuleiro)
    return registro


async def mcp_motor(nome: str, **argumentos):
    """O motor é compartilhado com o treinador. Uma fila ocupada recebe novas tentativas curtas."""
    for tentativa in range(3):
        try:
            return await services.mcp(nome, **argumentos)
        except HTTPException as erro:
            if erro.status_code != 503 or tentativa == 2:
                raise
            await asyncio.sleep(0.4 * (tentativa + 1))


async def jogar_ia(jogo: JogoSalvo, tabuleiro: chess.Board) -> None:
    inicio = perf_counter()
    resposta = await mcp_motor("jogar_stockfish", fen_inicial=jogo.fen_inicial,
                               lances=[l.uci for l in jogo.lances], dificuldade=jogo.dificuldade)

    try:
        lance = lance_legal(tabuleiro, resposta["uci"])
        selecao = SelecaoMotor.model_validate(resposta)
    except (ValueError, TypeError, KeyError, HTTPException) as erro:
        raise HTTPException(503, "O Stockfish não retornou uma jogada utilizável.") from erro
    registro = aplicar(jogo, tabuleiro, lance, selecao)
    registro.tempos["adversario_ms"] = round((perf_counter() - inicio) * 1000)


async def avaliar(jogo: JogoSalvo, tabuleiro: chess.Board, lance: LanceJogo) -> None:
    inicio = perf_counter()
    item = None
    if jogo.partida_analise_id:
        item = repositorio.avaliacao_da_revisao(jogo.partida_analise_id, lance.indice, perfil_analise())
    try:
        if item is None:
            regras.exportar(jogo, tabuleiro)
            (item,) = await mcp_motor("analisar_partida", pgn=jogo.pgn, cor_do_jogador=jogo.cor_do_jogador,
                                      inicio=lance.indice - 1, limite=1)
            lance.tempos["avaliacao_ms"] = round((perf_counter() - inicio) * 1000)
        campos = ("indice", "numero", "cor", "san", "uci", "fen_antes", "fen_depois")
        if any(item[campo] != getattr(lance, campo) for campo in campos) or item["perspectiva"] != lance.cor:
            raise ValueError("O motor avaliou outro lance.")
        perfil = item.get("perfil_analise")
        if perfil is not None and not isinstance(perfil, str):
            raise ValueError("O motor retornou um perfil de análise inválido.")
        lance.avaliacao = Movimento.model_validate({**item, "explicacao": None})
        lance.perfil_avaliacao = perfil
    except (ValueError, TypeError, KeyError) as erro:
        raise HTTPException(503, "Não foi possível avaliar o lance com o Stockfish.") from erro
    config = jogo.configuracoes
    lance.sugerir_explicacao = config.modo_treinador and (
        config.frequencia_explicacoes == "todos" or
        (config.frequencia_explicacoes == "erros" and lance.avaliacao.classe in {"imprecisao", "erro", "erro_grave"})
    )


def confirmar(jogo: JogoSalvo, token: str, tabuleiro: chess.Board,
              *, agendar: repositorio.AgendarExplicacao | None = None) -> EstadoJogo:
    partida = regras.exportar(jogo, tabuleiro)
    jogo.versao += 1
    repositorio.confirmar(jogo, token, regras.preparar_revisao(jogo, partida), agendar=agendar)
    return estado(jogo)


async def iniciar(entrada: IniciarJogo, sessao: str | None = None) -> EstadoJogo:
    tabuleiro = chess.Board()
    cor = choice(("white", "black")) if entrada.cor_do_jogador == "random" else entrada.cor_do_jogador
    jogo = JogoSalvo(id=uuid4().hex, criado_em=db.agora(), cor_do_jogador=cor, usuario=repositorio.perfil_da_sessao(sessao),
                     dificuldade=entrada.dificuldade, fen=tabuleiro.fen(), fen_inicial=tabuleiro.fen(),
                     configuracoes=Configuracoes.model_validate(entrada.model_dump(include=set(Configuracoes.model_fields))))
    if jogo.cor_do_jogador == "black":
        async with prazo_motor():
            await jogar_ia(jogo, tabuleiro)
    regras.exportar(jogo, tabuleiro)
    repositorio.criar(jogo, sessao)
    return estado(jogo)


async def avaliar_posicao(id_: str, versao: int, recomendar: bool) -> AvaliacaoPosicao:
    def posicao_atual() -> JogoSalvo:
        jogo, processando = repositorio.obter(id_)
        if processando or jogo.versao != versao or jogo.status != "em_andamento":
            raise HTTPException(409, "A posição mudou. Consulte a partida atual.")
        return jogo

    jogo = posicao_atual()
    async with prazo_motor():
        dados = await mcp_motor("analisar_posicao", fen=jogo.fen, profundidade=12, multipv=1)
    posicao_atual()
    try:
        melhor = dados["melhores_lances"][0] if recomendar else None
        return AvaliacaoPosicao(versao=versao, avaliacao=normalizar_avaliacao(dados, jogo.cor_do_jogador),
                                dica={"san": melhor["san"], "uci": melhor["uci"]} if melhor else None)
    except (KeyError, IndexError, TypeError, ValueError) as erro:
        raise HTTPException(503, "A avaliação do Stockfish está indisponível.") from erro


async def mover(id_: str, versao: int, uci: str, *, agendar: repositorio.AgendarExplicacao) -> EstadoJogo:
    with repositorio.reservar(id_, versao) as (jogo, token):
        tabuleiro = reproduzir(jogo)
        validar_vez(jogo, tabuleiro)
        lance = aplicar(jogo, tabuleiro, lance_legal(tabuleiro, uci))
        async with prazo_motor():
            if jogo.configuracoes.analise_automatica:
                await avaliar(jogo, tabuleiro, lance)
            if jogo.status == "em_andamento":
                await jogar_ia(jogo, tabuleiro)
        return confirmar(jogo, token, tabuleiro, agendar=agendar)


def lance_do_jogador(jogo: JogoSalvo, indice: int) -> LanceJogo:
    if not 1 <= indice <= len(jogo.lances):
        raise HTTPException(404, "Lance não encontrado na partida.")
    lance = jogo.lances[indice - 1]
    if lance.autor != "jogador":
        raise HTTPException(422, "O feedback pedagógico está disponível para lances do jogador.")
    return lance


async def avaliar_indice(id_: str, versao: int, indice: int) -> EstadoJogo:
    with repositorio.reservar(id_, versao) as (jogo, token):
        lance = lance_do_jogador(jogo, indice)
        tabuleiro = reproduzir(jogo)
        if lance.avaliacao is not None:
            return estado(jogo)
        async with prazo_motor():
            await avaliar(jogo, tabuleiro, lance)
        return confirmar(jogo, token, tabuleiro)


def desistir(id_: str, versao: int) -> EstadoJogo:
    with repositorio.reservar(id_, versao) as (jogo, token):
        tabuleiro = reproduzir(jogo)
        validar_vez(jogo, tabuleiro)
        jogo.status, jogo.motivo = "encerrada", "desistencia"
        jogo.resultado = "0-1" if jogo.cor_do_jogador == "white" else "1-0"
        return confirmar(jogo, token, tabuleiro)


def reivindicar(id_: str, versao: int, uci: str | None) -> EstadoJogo:
    with repositorio.reservar(id_, versao) as (jogo, token):
        tabuleiro = reproduzir(jogo)
        validar_vez(jogo, tabuleiro)
        if uci is not None:
            tabuleiro.push(lance_legal(tabuleiro, uci))
        motivo = regras.motivo_empate(tabuleiro)
        if uci is not None:
            tabuleiro.pop()
        if motivo is None:
            raise HTTPException(422, "A posição não permite reivindicar empate desta forma.")
        jogo.status, jogo.motivo, jogo.resultado = "encerrada", motivo, "1/2-1/2"
        return confirmar(jogo, token, tabuleiro)


def configurar(id_: str, versao: int, alteracoes: dict) -> EstadoJogo:
    """Altera a assistência durante a partida. Vale para os próximos lances."""
    with repositorio.reservar(id_, versao) as (jogo, token):
        tabuleiro = reproduzir(jogo)
        if jogo.status != "em_andamento":
            raise HTTPException(409, "A partida já foi encerrada.")
        valores = {**jogo.configuracoes.model_dump(), **{k: v for k, v in alteracoes.items() if v is not None}}
        if alteracoes.get("modo_assistencia"):
            valores.pop("frequencia_explicacoes")
        jogo.configuracoes = Configuracoes.model_validate(valores)
        return confirmar(jogo, token, tabuleiro)
