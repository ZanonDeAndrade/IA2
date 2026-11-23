"""API HTTP do treinador Lance a Lance."""

import asyncio
from contextlib import asynccontextmanager, closing
import logging
import os

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Path, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agent.graph import responder_chat_async
from backend import db, services
from backend.jogo import treinador
from backend.jogo.api import router as jogo_router, router_treinador
from backend.schemas import (
    Chat, Erro, Explicacao, Importacao, Importadas, Lance, Partida, Pergunta, Relatorio, Tarefa, TarefaCriada,
)
from mcp_server.tools.engine import perfil_analise
from mcp_server.tools.pgn import ler_partida, metadados

load_dotenv(db.RAIZ / ".env")
LOGGER = logging.getLogger(__name__)


class LimiteCorpo:
    """Limita cada POST inclusive quando o cliente usa transferência em partes."""

    def __init__(self, app, maximo: int = 1024 * 1024):
        self.app, self.maximo = app, maximo

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        corpo = bytearray()
        while True:
            mensagem = await receive()
            if mensagem["type"] == "http.disconnect":
                return
            corpo.extend(mensagem.get("body", b""))
            if len(corpo) > self.maximo:
                await JSONResponse({"detail": "Corpo da requisição excede 1 MiB."}, status_code=413)(scope, receive, send)
                return
            if not mensagem.get("more_body"):
                break

        async def ler():
            nonlocal corpo
            if corpo is None:
                return await receive()
            dados = bytes(corpo)
            corpo = None
            return {"type": "http.request", "body": dados, "more_body": False}

        await self.app(scope, ler, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    for nome in ("agent.mcp", "agent.graph", "agent.treinador", "backend.jogo.treinador"):
        logger = logging.getLogger(nome)
        if not logger.hasHandlers():
            logger.addHandler(logging.StreamHandler())
        logger.setLevel(logging.INFO)
    with closing(db.conectar()) as conn:
        db.inicializar_banco(conn)
        db.interromper_tarefas(conn)
    app.state.fila_motor = asyncio.Lock()
    app.state.fila_llm = asyncio.Semaphore(2)
    app.state.treinador = await treinador.iniciar_fila(app.state.fila_llm)
    try:
        yield
    finally:
        await treinador.encerrar_fila()


app = FastAPI(title="Lance a Lance API", version="0.2.0", lifespan=lifespan,
              responses={503: {"model": Erro, "description": "Dependência indisponível"}})
app.add_middleware(LimiteCorpo)
app.add_middleware(CORSMiddleware, allow_origins=[
    origem.strip() for origem in (os.getenv("CORS_ORIGENS") or "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if origem.strip()
], allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Sessao-Jogo"])
app.include_router(jogo_router)
app.include_router(router_treinador)


@app.exception_handler(Exception)
async def erro_interno(request: Request, erro: Exception):
    LOGGER.error("Erro interno HTTP %s (%s)", request.method, type(erro).__name__)
    return JSONResponse({"detail": "Falha interna no servidor."}, status_code=500)


@app.get("/healthz")
async def health() -> dict:
    with closing(db.conectar()) as conn:
        conn.execute("SELECT 1 FROM partidas LIMIT 1").fetchone()
    if url := os.getenv("MCP_HEALTH_URL"):
        try:
            async with httpx.AsyncClient(timeout=2) as cliente:
                (await cliente.get(url)).raise_for_status()
        except httpx.HTTPError as erro:
            raise HTTPException(503, "Aguardando o servidor MCP.") from erro
    return {"status": "ok"}


@app.post("/api/partidas/importar", status_code=201, response_model=Importadas, responses={404: {"model": Erro}, 502: {"model": Erro}})
async def importar_partidas(entrada: Importacao) -> dict:
    """Importa partidas públicas do Chess.com ou valida e salva uma partida em PGN."""
    if entrada.pgn is None:
        partidas = await services.mcp("buscar_partidas", usuario=entrada.usuario, max=entrada.max, ritmo=entrada.ritmo)
    else:
        try:
            jogo = ler_partida(entrada.pgn)
        except ValueError as erro:
            raise HTTPException(422, str(erro)) from erro
        partida = metadados(jogo, entrada.pgn, entrada.usuario, entrada.cor_do_jogador)
        partida["chave_pgn"] = [jogo.board().fen(), list(m.uci() for m in jogo.mainline_moves()),
                                partida["jogadores"], partida["resultado"], partida["data"]]
        partidas = [partida]
    perfil = services.perfil_explicacao()
    registros = []
    with closing(db.conectar()) as conn:
        for partida in partidas:
            id_ = db.salvar_partida(conn, partida)
            dados = db.obter_partida(conn, id_, perfil)
            registros.append({k: dados[k] for k in ("id", "url", "data", "ritmo", "cor_do_jogador",
                              "adversario", "resultado", "abertura", "total_lances", "status_analise", "jogadores")}
                             | {"erros_graves": services.resumo(dados)["erros_graves"]})
    return {"usuario": entrada.usuario or (partidas[0]["usuario"] if partidas else None), "partidas": registros}


@app.post("/api/partidas/{id}/analisar", status_code=202, response_model=TarefaCriada, responses={404: {"model": Erro}, 429: {"model": Erro}})
def analisar_partida(id: str, request: Request, tarefas: BackgroundTasks) -> dict:
    """Enfileira análise pelo MCP ou devolve a tarefa atual, incluindo o cache."""
    assinatura = perfil_analise()
    with closing(db.conectar()) as conn:
        try:
            tarefa, criar = db.iniciar_tarefa(conn, id, assinatura)
        except KeyError as erro:
            raise HTTPException(404, "Partida não encontrada.") from erro
        except OverflowError as erro:
            raise HTTPException(429, str(erro)) from erro
        if criar:
            partida = db.obter_partida(conn, id)
            tarefas.add_task(services.analisar_em_segundo_plano, tarefa, partida, assinatura, request.app.state.fila_motor)
    return {"tarefa_id": tarefa}


@app.get("/api/partidas/{id}", response_model=Partida, responses={404: {"model": Erro}})
def obter_partida(id: str) -> dict:
    with closing(db.conectar()) as conn:
        partida = db.obter_partida(conn, id, services.perfil_explicacao())
    if partida is None:
        raise HTTPException(404, "Partida não encontrada.")
    return services.partida_publica(partida)


@app.get("/api/tarefas/{id}", response_model=Tarefa, responses={404: {"model": Erro}})
def obter_tarefa(id: str) -> dict:
    with closing(db.conectar()) as conn:
        tarefa = db.obter_tarefa(conn, id)
    if tarefa is None:
        raise HTTPException(404, "Tarefa não encontrada.")
    return tarefa


@app.post("/api/explicar", response_model=Explicacao, responses={504: {"model": Erro}})
async def explicar(entrada: Lance, request: Request) -> dict:
    try:
        return await asyncio.wait_for(services.explicacao(entrada.fen, entrada.lance_jogado, request.app.state.fila_llm), 150)
    except TimeoutError as erro:
        raise HTTPException(504, "O prazo da explicação foi excedido.") from erro


@app.post("/api/chat", response_model=Chat, responses={504: {"model": Erro}})
async def chat(entrada: Pergunta, request: Request) -> dict:
    tabuleiro = services.tabuleiro_valido(entrada.fen)
    contexto = {}
    if referencia := entrada.lance_selecionado:
        contexto["lance_selecionado"] = services.contexto_chat(tabuleiro.fen(), referencia.partida_id, referencia.indice)
    try:
        async with asyncio.timeout(150), request.app.state.fila_llm:
            resposta = await responder_chat_async(
                entrada.fen, entrada.pergunta, [mensagem.model_dump() for mensagem in entrada.historico],
                **contexto,
            )
    except TimeoutError as erro:
        raise HTTPException(504, "O prazo do chat foi excedido.") from erro
    return {"fen": entrada.fen, "pergunta": entrada.pergunta, **resposta,
            "status": "ok" if resposta["validada"] else "indisponivel"}


@app.get("/api/relatorio/{usuario}", response_model=Relatorio)
async def obter_relatorio(usuario: str = Path(min_length=1, max_length=100)) -> dict:
    if not (limpo := usuario.strip()) or not limpo.isprintable():
        raise HTTPException(422, "Identificador de jogador inválido.")
    return await services.relatorio(limpo)
