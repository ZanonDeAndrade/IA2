"""Orquestra MCP, cache e os grafos existentes para a API."""

import asyncio
from collections import Counter
from contextlib import AsyncExitStack, closing
from hashlib import sha256
from itertools import groupby
import logging
import os
from pathlib import Path
from statistics import mean
from typing import Any

from fastapi import HTTPException

from agent.graph import explicar_erro_async
from agent.mcp import ErroFerramenta, Ferramentas, sessao_mcp
from agent.validator import ler_fen
from backend import db
from mcp_server.tools.engine import dados_classificacao, normalizar_avaliacao, perfil_analise
from mcp_server.tools.puzzles import ROTULOS, TAGS

LOGGER = logging.getLogger(__name__)
ERROS_MCP = {
    "CHESSCOM_USUARIO_INEXISTENTE": (404, "Usuário do Chess.com não encontrado."),
    "CHESSCOM_USER_AGENT_AUSENTE": (503, "Configure CHESSCOM_USER_AGENT para importar do Chess.com."),
    "CHESSCOM_INDISPONIVEL": (502, "O Chess.com está indisponível. Tente novamente ou envie um PGN."),
    "PUZZLES_BASE_AUSENTE": (503, "Prepare a base local de puzzles."),
    "PUZZLES_BASE_INVALIDA": (503, "A base local de puzzles precisa ser reconstruída."),
}


def tabuleiro_valido(fen: str):
    try:
        return ler_fen(fen)
    except ValueError as erro:
        raise HTTPException(422, "Posição FEN inválida.") from erro


def contexto_chat(fen: str, partida_id: str, indice: int) -> dict:
    with closing(db.conectar()) as conn:
        lance = db.obter_lance_da_partida(conn, partida_id, indice)
        if lance is None or fen not in (lance["fen_antes"], lance["fen_depois"]):
            raise HTTPException(422, "O lance informado não corresponde à posição atual da partida.")
        explicacao = db.obter_explicacao(conn, lance["fen_antes"], lance["san"], perfil_explicacao())
    retorno = {
        "jogada_da_partida": lance["san"], "classe": lance["classe"],
        "momento": "antes" if fen == lance["fen_antes"] else "depois",
        "fen_apos_lance": lance["fen_depois"],
    }
    if explicacao and explicacao.get("validada") and explicacao["tema"] != "outro":
        retorno.update(tema=explicacao["tema"], tema_label=explicacao["tema_label"])
    return retorno


async def mcp(nome: str, **argumentos) -> Any:
    try:
        async with sessao_mcp() as disponiveis:
            try:
                return await Ferramentas(disponiveis).chamar(nome, **argumentos)
            except ErroFerramenta as erro:
                codigo = str(erro)
    except Exception as erro:
        raise HTTPException(503, f"Ferramenta indisponível: {nome}.") from erro
    status, mensagem = ERROS_MCP[codigo]
    raise HTTPException(status, mensagem)


def perfil_explicacao() -> str:
    variaveis = ("LLM_PROVIDER", "LLM_MODEL", "LLM_BASE_URL", "LLM_TEMPERATURA", "EMBEDDING_MODEL", "LLM_REVISAO",
                 "LLM_RACIOCINIO", "LLM_MAX_TOKENS", "LLM_JSON_MODE")
    pasta = db.RAIZ / "agent" / "prompts"
    dados = sha256(repr([os.getenv(nome) for nome in variaveis]).encode())
    for caminho in sorted([*pasta.glob("*.md"), *(db.RAIZ / "knowledge_base").glob("*.md")]):
        dados.update(caminho.read_bytes())
    dados.update(perfil_analise().encode())
    return dados.hexdigest()


def resumo(partida: dict) -> dict:
    lances = [lance for lance in partida["lances"] if lance["cor"] == partida["cor_do_jogador"]]
    classes = Counter(lance["classe"] for lance in lances)
    return {
        "imprecisoes": classes["imprecisao"], "erros": classes["erro"], "erros_graves": classes["erro_grave"],
        "precisao": round(100 - mean(max(0, lance["queda"]) for lance in lances), 1) if lances else None,
        "lances_do_jogador_analisados": len(lances),
    }


def partida_publica(partida: dict) -> dict:
    curva = []
    for indice, lance in enumerate(partida["lances"]):
        if indice == 0:
            inicial = _avaliacao_brancas(lance, "antes")
            curva.append({"lance": 0, **inicial})
        curva.append({"lance": lance["indice"], **_avaliacao_brancas(lance, "depois")})
    dados = {k: v for k, v in partida.items() if k != "analise"}
    totais = resumo(partida)
    return {**dados, "resumo": totais, "erros_graves": totais["erros_graves"], "curva_avaliacao": curva}


def _avaliacao_brancas(lance: dict, momento: str) -> dict:
    aval = normalizar_avaliacao(
        {"avaliacao": lance[f"avaliacao_{momento}"], "perspectiva": lance["perspectiva"]}, "white",
    )
    return {"cp": aval["valor"] if aval["tipo"] == "cp" else None, "avaliacao": aval, "perspectiva": "white"}


async def analisar_em_segundo_plano(id_tarefa: str, partida: dict, assinatura: str, fila: asyncio.Lock) -> None:
    feita = 0
    try:
        async with fila, AsyncExitStack() as recursos:
            with closing(db.conectar()) as conn:
                db.atualizar_tarefa(conn, id_tarefa, {"status": "em_andamento", "atual": feita})
                reaproveitados = db.avaliacoes_do_treino(conn, partida["id"], assinatura)
            ferramentas = None
            total = partida["total_lances"]
            for inicio in range(0, total, 4):
                fim = min(inicio + 4, total)
                lances = []
                for ja_avaliados, trecho in groupby(range(inicio + 1, fim + 1), key=reaproveitados.__contains__):
                    indices = list(trecho)
                    if ja_avaliados:
                        lances.extend(reaproveitados[indice] for indice in indices)
                        continue
                    if ferramentas is None:
                        ferramentas = Ferramentas(await recursos.enter_async_context(sessao_mcp()))
                    novos = await ferramentas.chamar(
                        "analisar_partida", pgn=partida["pgn"], cor_do_jogador="ambas",
                        inicio=indices[0] - 1, limite=len(indices),
                    )
                    if not isinstance(novos, list) or [lance["indice"] for lance in novos] != indices:
                        raise ValueError("Resposta incompleta de analisar_partida.")
                    lances.extend(novos)
                with closing(db.conectar()) as conn:
                    concluida = fim == total
                    db.salvar_analise(conn, partida["id"], lances, assinatura if concluida else None, id_tarefa)
                feita = fim
    except (Exception, asyncio.CancelledError) as erro:
        LOGGER.warning("Falha na análise tarefa=%s (%s)", id_tarefa, type(erro).__name__)
        with closing(db.conectar()) as conn:
            db.atualizar_tarefa(conn, id_tarefa, {"status": "erro", "atual": feita,
                                "erro": "Análise interrompida ou Stockfish/MCP indisponível. Tente novamente."})
        if isinstance(erro, asyncio.CancelledError):
            raise


async def explicacao(fen: str, jogado: str, fila: asyncio.Semaphore, *, analise: dict | None = None,
                     forcar: bool = False, treino: dict | None = None) -> dict:
    tabuleiro = tabuleiro_valido(fen)
    try:
        movimento = tabuleiro.parse_san(jogado)
        if not tabuleiro.is_legal(movimento):
            raise ValueError
    except ValueError as erro:
        raise HTTPException(422, "O lance não é legal no FEN informado.") from erro
    fen, san = tabuleiro.fen(), tabuleiro.san(movimento)
    perfil = perfil_explicacao()
    if analise is not None:
        # O treinador do jogo explica a avaliação exibida, mesmo que já exista
        # uma explicação para outra variante da mesma posição.
        perfil += ":jogo:" + sha256(repr((analise, treino)).encode()).hexdigest()
    async with fila:
        with closing(db.conectar()) as conn:
            # forcar atende a um pedido explícito de nova geração.
            cache = None if forcar else db.obter_explicacao(conn, fen, san, perfil)
            if cache is not None:
                return {**cache, "cache": True}
            dados = analise if analise is not None else db.obter_lance_analisado(conn, fen, san, perfil_analise())
        ferramentas_motor = []
        if dados is None:
            cor = "white" if tabuleiro.turn else "black"
            tabuleiro.push(movimento)
            antes = await mcp("analisar_posicao", fen=fen)
            depois = await mcp("analisar_posicao", fen=tabuleiro.fen(), multipv=1)
            if not antes.get("linha_principal"):
                raise HTTPException(503, "O Stockfish não devolveu uma variante principal.")
            dados = {**dados_classificacao(antes, depois, cor), "linha_motor": antes["linha_principal"],
                     "melhor_lance_uci": antes["melhores_lances"][0]["uci"]}
            ferramentas_motor = ["analisar_posicao"]
        linha = dados["linha_motor"]
        resposta = await explicar_erro_async(fen, san, linha[0], linha, **({"treino": treino} if treino else {}))
        resultado = {**resposta, "fen": fen, "lance_jogado": san, "melhor_lance": linha[0],
                     "melhor_lance_uci": dados["melhor_lance_uci"], "classe": dados["classe"],
                     "queda": dados["queda"], "cache": False,
                     "ferramentas_usadas": list(dict.fromkeys([*ferramentas_motor, *resposta["ferramentas_usadas"]]))}
        if resultado["validada"] and not resultado["fallback"]:
            with closing(db.conectar()) as conn:
                db.salvar_explicacao(conn, fen, san, resultado, perfil)
        return resultado


async def relatorio(usuario: str) -> dict:
    with closing(db.conectar()) as conn:
        partidas = db.partidas_analisadas(conn, usuario, perfil_explicacao())
        # Partidas jogadas contra a IA aproveitam as explicações do treinador.
        treino = {partida["id"]: db.explicacoes_do_treino(conn, partida["id"]) for partida in partidas}
    partidas.sort(key=lambda item: (item["data"] or "", item["id"]))
    ratings = [rating for item in partidas if isinstance(
        rating := item["jogadores"][item["cor_do_jogador"]].get("rating"), int)]
    rating = round(mean(ratings)) if ratings else None
    temas = Counter()
    sem_tema = 0
    evolucao = []
    for partida in partidas:
        evolucao.append({"partida_id": partida["id"], "data": partida["data"], **resumo(partida)})
        for lance in partida["lances"]:
            if lance["cor"] != partida["cor_do_jogador"] or lance["classe"] not in {"erro", "erro_grave"}:
                continue
            explicada = lance["explicacao"] or treino[partida["id"]].get(lance["indice"]) or {}
            tag = TAGS.get(explicada.get("tema"))
            if explicada.get("validada") and tag:
                temas[tag] += 1
            else:
                sem_tema += 1
    ranking = [{"tema": tag, "tema_label": ROTULOS[tag], "erros": n} for tag, n in temas.most_common()]
    puzzles, aviso = [], None
    if partidas:
        try:
            minimo, maximo = (max(0, rating - 250), min(4000, rating + 250)) if rating else (800, 1800)
            tags = [tema["tema"] for tema in ranking[:3]]
            puzzles = await mcp("buscar_puzzles", temas=tags, rating_min=minimo, rating_max=maximo)
            if not puzzles:
                aviso = (f"Nenhum puzzle do recorte corresponde aos temas na faixa de rating {minimo}–{maximo}."
                         if tags else f"Nenhum puzzle do recorte está na faixa de rating {minimo}–{maximo}.")
        except HTTPException as erro:
            aviso = erro.detail
    return {"usuario": usuario, "partidas_analisadas": len(partidas), "rating_estimado": rating,
            "temas_fracos": ranking, "erros_sem_tema": sem_tema, "evolucao": evolucao,
            "puzzles_recomendados": puzzles, "puzzles_personalizados_por_tema": bool(ranking),
            "aviso_puzzles": aviso}
