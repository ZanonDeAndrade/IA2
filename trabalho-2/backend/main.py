"""API do Lance a Lance (FastAPI).

Endpoints consumidos pela interface, no formato dos mocks em
``frontend/src/mocks/``. A análise de uma partida roda em segundo plano
(``BackgroundTasks``) e a interface consulta o progresso a cada 2 s.

Execução (a partir de ``trabalho-2/``):
    uvicorn backend.main:app --reload --port 8000
Documentação interativa: http://localhost:8000/docs
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import chess
import chess.pgn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

RAIZ = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ / ".env")

from backend import agente, db, mcp_cliente  # noqa: E402
from mcp_server.tools.classificacao import chance_da_avaliacao, classificar, precisao  # noqa: E402
from mcp_server.tools.temas import TEMAS_DO_AGENTE, rotulo  # noqa: E402

log = logging.getLogger("lance-a-lance.backend")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

CLASSES_EXPLICADAS = {"erro", "erro_grave"}
CP_GRAFICO = 1500  # limite do eixo do gráfico de avaliação (mate vira ±1500)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.inicializar_banco()
    yield


app = FastAPI(
    title="Lance a Lance API",
    description="Treinador de xadrez com IA: análise de partidas, explicações e relatórios.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _erro_ferramenta(e: mcp_cliente.ErroFerramenta) -> HTTPException:
    texto = str(e)
    baixo = texto.lower()
    if "não encontrad" in baixo:
        return HTTPException(status.HTTP_404_NOT_FOUND, texto)
    if "indisponível" in baixo or "stockfish" in baixo or "não foi implementada" in baixo:
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, texto)
    return HTTPException(status.HTTP_400_BAD_REQUEST, texto)


# --------------------------------------------------------------------------- #
# Modelos de entrada
# --------------------------------------------------------------------------- #

class ImportarEntrada(BaseModel):
    usuario: str | None = Field(None, description="Usuário do Chess.com")
    max: int = Field(10, ge=1, le=50)
    ritmo: str | None = Field(None, description="bullet, blitz, rapid ou daily")
    pgn: str | None = Field(None, description="Partida colada em PGN")
    cor_do_jogador: Literal["white", "black"] | None = Field(None, description="Só com PGN; padrão white")

    @model_validator(mode="after")
    def _um_dos_dois(self):
        if bool(self.usuario) == bool(self.pgn):
            raise ValueError("Informe um usuário do Chess.com ou um PGN (apenas um dos dois).")
        return self


class ExplicarEntrada(BaseModel):
    fen: str = Field(..., description="Posição antes do lance")
    lance_jogado: str = Field(..., description="Lance jogado (SAN ou UCI)")


class ChatEntrada(BaseModel):
    fen: str
    pergunta: str = Field(..., min_length=1, max_length=1000)
    historico: list[dict[str, Any]] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Montagem das respostas (formato dos mocks)
# --------------------------------------------------------------------------- #

def _status_analise(partida_id: str, analise: list | None) -> tuple[str, str | None]:
    if analise is not None:
        return "concluida", None
    tarefa = db.ultima_tarefa(partida_id)
    if tarefa is None:
        return "pendente", None
    return tarefa["status"], tarefa["id"]


def _contagem(lances: list[dict]) -> Counter:
    return Counter(l["classe"] for l in lances if l["do_jogador"])


def _resumo_partida(p: dict[str, Any]) -> dict[str, Any]:
    """Item de ``frontend/src/mocks/partidas.json``."""
    analise = db.obter_analise(p["id"])
    status_analise, tarefa_id = _status_analise(p["id"], analise)
    return {
        "id": p["id"],
        "url": p.get("url"),
        "data": p.get("data"),
        "ritmo": p.get("ritmo"),
        "cor_do_jogador": p["cor_do_jogador"],
        "adversario": p.get("adversario"),
        "resultado": p.get("resultado"),
        "resultado_do_jogador": p.get("resultado_do_jogador"),
        "abertura": p.get("abertura"),
        "total_lances": p.get("total_lances"),
        "erros_graves": _contagem(analise)["erro_grave"] if analise is not None else None,
        "status_analise": status_analise,
        "tarefa_id": tarefa_id,
        "origem": p["origem"],
    }


def _explicacao_publica(exp: dict[str, Any] | None) -> dict[str, Any] | None:
    if exp is None:
        return None
    return {k: exp.get(k) for k in ("tema", "tema_label", "texto", "ficha", "ferramentas_usadas",
                                    "tentativas", "validada", "origem")}


def _lance_publico(l: dict[str, Any]) -> dict[str, Any]:
    """Lance de ``frontend/src/mocks/partida.json`` (mais uci e melhor_lance_uci para as setas)."""
    return {
        "indice": l["indice"], "numero": l["numero"], "cor": l["cor"],
        "san": l["san"], "uci": l["uci"],
        "fen_antes": l["fen_antes"], "fen_depois": l["fen_depois"],
        "cp_antes": l["cp_antes"], "cp_depois": l["cp_depois"],
        "mate_antes": l["mate_antes"], "mate_depois": l["mate_depois"],
        "chance_vitoria_antes": l["chance_vitoria_antes"], "chance_vitoria_depois": l["chance_vitoria_depois"],
        "queda": l["queda"], "classe": l["classe"],
        "melhor_lance": l["melhor_lance"], "melhor_lance_uci": l["melhor_lance_uci"],
        "linha_motor": l["linha_motor"],
        "explicacao": _explicacao_publica(db.obter_explicacao(l["fen_antes"], l["uci"])),
    }


def _partida_de_pgn(pgn: str, cor: str | None) -> dict[str, Any]:
    jogo = chess.pgn.read_game(io.StringIO(pgn))
    if jogo is None or jogo.errors or not any(True for _ in jogo.mainline_moves()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "PGN inválido: não foi possível ler os lances da partida.")
    h = jogo.headers
    pgn_limpo = str(jogo)
    cor = cor or "white"
    resultado = h.get("Result", "*")
    vencedor = {"1-0": "white", "0-1": "black"}.get(resultado)
    return {
        "id": "pgn-" + hashlib.sha1(pgn_limpo.encode()).hexdigest()[:12],
        "usuario": None,
        "origem": "pgn",
        "pgn": pgn_limpo,
        "cor_do_jogador": cor,
        "url": None,
        "data": (h.get("UTCDate") or h.get("Date") or "").replace(".", "-") or None,
        "ritmo": None,
        "adversario": h.get("Black" if cor == "white" else "White"),
        "resultado": resultado,
        "resultado_do_jogador": ("empate" if resultado == "1/2-1/2" else None if vencedor is None
                                 else "vitoria" if vencedor == cor else "derrota"),
        "abertura": h.get("Opening") or h.get("ECO"),
        "total_lances": (sum(1 for _ in jogo.mainline_moves()) + 1) // 2,
    }


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

@app.get("/api/saude")
async def saude() -> dict:
    """Situação dos componentes (para o estado de erro da interface)."""
    mcp_ok, erro_mcp = True, None
    try:
        await mcp_cliente.chamar("validar_lances", {"fen": chess.STARTING_FEN, "lances": ["e4"]})
    except Exception as e:  # noqa: BLE001
        mcp_ok, erro_mcp = False, str(e)
    return {"api": True, "mcp": mcp_ok, "erro_mcp": erro_mcp, "agente": agente.agente_disponivel()}


@app.post("/api/partidas/importar", status_code=status.HTTP_201_CREATED)
async def importar_partidas(entrada: ImportarEntrada) -> dict:
    """Busca as partidas de um usuário do Chess.com ou recebe um PGN colado.

    Corpo: ``{"usuario": str, "max": int, "ritmo"?: str}`` ou ``{"pgn": str, "cor_do_jogador"?: str}``.
    Resposta: ``frontend/src/mocks/partidas.json``.
    """
    if entrada.pgn:
        p = _partida_de_pgn(entrada.pgn, entrada.cor_do_jogador)
        db.salvar_partida(p)
        return {"usuario": None, "partidas": [_resumo_partida(p)]}

    try:
        partidas = await mcp_cliente.chamar("buscar_partidas", {
            "usuario": entrada.usuario, "max": entrada.max, "ritmo": entrada.ritmo})
    except mcp_cliente.ErroFerramenta as e:
        raise _erro_ferramenta(e) from e

    resumos = []
    for x in partidas:
        p = {**x, "usuario": entrada.usuario.lower(), "origem": "chesscom"}
        db.salvar_partida(p)
        resumos.append(_resumo_partida(p))
    return {"usuario": entrada.usuario, "partidas": resumos}


@app.get("/api/partidas")
async def listar_partidas(usuario: str) -> dict:
    """Partidas já importadas de um usuário (sem chamar o Chess.com de novo)."""
    return {"usuario": usuario, "partidas": [_resumo_partida(p) for p in db.partidas_do_usuario(usuario)]}


@app.post("/api/partidas/{id}/analisar", status_code=status.HTTP_202_ACCEPTED)
async def analisar_partida(id: str, background: BackgroundTasks, refazer: bool = False) -> dict:
    """Inicia a análise em segundo plano e devolve a tarefa (com ``tarefa_id``).

    Se a partida já foi analisada (cache), a tarefa volta concluída na hora.
    Resposta: ``frontend/src/mocks/tarefa.json``.
    """
    partida = db.obter_partida(id)
    if not partida:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Partida não encontrada. Importe-a primeiro.")
    ultima = db.ultima_tarefa(id)
    if ultima and ultima["status"] in {"pendente", "em_andamento"}:
        return ultima
    tarefa = db.criar_tarefa(id)
    if db.obter_analise(id) is not None and not refazer:
        db.atualizar_tarefa(tarefa["id"], status="concluida", etapa="cache", lance_atual=1, total_lances=1)
        return db.obter_tarefa(tarefa["id"])
    background.add_task(_rodar_analise, tarefa["id"], partida)
    return tarefa


@app.get("/api/tarefas/{id}")
async def obter_tarefa(id: str) -> dict:
    """Progresso de uma análise (``frontend/src/mocks/tarefa.json``)."""
    t = db.obter_tarefa(id)
    if not t:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tarefa não encontrada.")
    return t


@app.get("/api/partidas/{id}")
async def obter_partida(id: str) -> dict:
    """Partida com lances, avaliações, classes e explicações (``frontend/src/mocks/partida.json``).

    ``lances`` traz só os lances do jogador; ``todos_lances`` traz a partida inteira
    (para navegar no tabuleiro) e ``curva_avaliacao`` um ponto por meio-lance,
    do ponto de vista do jogador.
    """
    p = db.obter_partida(id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Partida não encontrada.")
    analise = db.obter_analise(id)
    status_analise, tarefa_id = _status_analise(id, analise)
    resposta: dict[str, Any] = {
        "id": p["id"], "usuario": p.get("usuario"), "cor_do_jogador": p["cor_do_jogador"],
        "adversario": p.get("adversario"), "resultado": p.get("resultado"),
        "resultado_do_jogador": p.get("resultado_do_jogador"), "abertura": p.get("abertura"),
        "data": p.get("data"), "ritmo": p.get("ritmo"), "url": p.get("url"), "pgn": p["pgn"],
        "status_analise": status_analise, "tarefa_id": tarefa_id,
        "resumo": None, "lances": [], "todos_lances": [], "curva_avaliacao": [],
    }
    if analise is None:
        return resposta

    do_jogador = [l for l in analise if l["do_jogador"]]
    contagem = _contagem(analise)
    resposta["resumo"] = {
        "imprecisoes": contagem["imprecisao"],
        "erros": contagem["erro"],
        "erros_graves": contagem["erro_grave"],
        "precisao": precisao([l["queda"] for l in do_jogador]),
    }
    resposta["lances"] = [_lance_publico(l) for l in do_jogador]
    resposta["todos_lances"] = [{k: l[k] for k in ("indice", "numero", "cor", "san", "uci", "fen_depois",
                                                   "classe", "do_jogador")} for l in analise]
    resposta["curva_avaliacao"] = [
        {"lance": l["indice"], "cp": max(-CP_GRAFICO, min(CP_GRAFICO, l["cp_depois"]))} for l in analise]
    return resposta


@app.post("/api/explicar")
async def explicar(entrada: ExplicarEntrada) -> dict:
    """Explica um lance específico (FEN + lance), com cache.

    Corpo: ``{"fen": str, "lance_jogado": str}``. Resposta: ``frontend/src/mocks/explicacao.json``.
    """
    try:
        validacao = await mcp_cliente.chamar("validar_lances", {"fen": entrada.fen, "lances": [entrada.lance_jogado]})
    except mcp_cliente.ErroFerramenta as e:
        raise _erro_ferramenta(e) from e
    lance = validacao[0]
    if not lance["legal"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"O lance {entrada.lance_jogado} não é legal nesta posição.")

    board = chess.Board(entrada.fen)
    cor = board.turn
    board.push(chess.Move.from_uci(lance["uci"]))
    try:
        antes, depois = await asyncio.gather(
            mcp_cliente.chamar("analisar_posicao", {"fen": entrada.fen, "multipv": 1}),
            mcp_cliente.chamar("analisar_posicao", {"fen": board.fen(), "multipv": 1}),
        )
    except mcp_cliente.ErroFerramenta as e:
        raise _erro_ferramenta(e) from e

    # analisar_posicao devolve a avaliação do lado a jogar: "depois" é do adversário.
    av_antes = antes["avaliacao"]
    av_depois = {"cp": -depois["avaliacao"]["cp"],
                 "mate": None if depois["avaliacao"]["mate"] is None else -depois["avaliacao"]["mate"]}
    chance_antes = chance_da_avaliacao(av_antes["cp"], av_antes["mate"])
    chance_depois = chance_da_avaliacao(av_depois["cp"], av_depois["mate"])
    melhor = antes["melhores_lances"][0] if antes["melhores_lances"] else None
    era_o_melhor = melhor is not None and melhor["uci"] == lance["uci"]
    queda = 0.0 if era_o_melhor else max(0.0, round(chance_antes - chance_depois, 2))
    classe = classificar(queda)

    base = {"fen": entrada.fen, "lance_jogado": lance["san"],
            "melhor_lance": melhor["san"] if melhor else None, "classe": classe, "queda": queda}
    if (pronta := db.obter_explicacao(entrada.fen, lance["uci"])):
        return {**base, **_explicacao_publica(pronta), "cache": True}

    ctx = {
        "fen_antes": entrada.fen, "fen_depois": board.fen(),
        "lance_jogado": lance["san"], "melhor_lance": base["melhor_lance"],
        "linha_motor": melhor["linha"] if melhor else [],
        "melhor_resposta": depois["melhores_lances"][0]["san"] if depois["melhores_lances"] else None,
        "chance_antes": chance_antes, "chance_depois": chance_depois,
        "queda": queda, "classe": classe, "cor": "white" if cor == chess.WHITE else "black",
    }
    exp = await agente.explicar_erro(ctx)
    db.salvar_explicacao(entrada.fen, lance["uci"], exp)
    return {**base, **_explicacao_publica(exp), "cache": False}


@app.post("/api/chat")
async def chat(entrada: ChatEntrada) -> dict:
    """Pergunta sobre a posição atual; a resposta lista as ferramentas usadas.

    Corpo: ``{"fen": str, "pergunta": str, "historico": list}``.
    Resposta: ``frontend/src/mocks/chat.json``. 503 enquanto o agente não existir.
    """
    try:
        chess.Board(entrada.fen)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"FEN inválido: {e}") from e
    try:
        r = await agente.conversar(entrada.fen, entrada.pergunta, entrada.historico)
    except agente.AgenteIndisponivel as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    return {"fen": entrada.fen, "pergunta": entrada.pergunta, **r}


@app.get("/api/relatorio/{usuario}")
async def obter_relatorio(usuario: str, puzzles_por_tema: int = 2) -> dict:
    """Temas fracos somados nas partidas analisadas e puzzles recomendados.

    Resposta: ``frontend/src/mocks/relatorio.json``.
    """
    temas: Counter[str] = Counter()
    evolucao, ratings = [], []
    for p in db.partidas_do_usuario(usuario):
        if p.get("rating_do_jogador"):
            ratings.append(p["rating_do_jogador"])
        analise = db.obter_analise(p["id"])
        if analise is None:
            continue
        for l in analise:
            if l["do_jogador"] and l["classe"] in CLASSES_EXPLICADAS:
                exp = db.obter_explicacao(l["fen_antes"], l["uci"]) or {}
                tema_lichess = TEMAS_DO_AGENTE.get(exp.get("tema") or "", {}).get("lichess")
                if tema_lichess:
                    temas[tema_lichess] += 1
        evolucao.append({
            "partida_id": p["id"], "data": p.get("data"),
            "precisao": precisao([l["queda"] for l in analise if l["do_jogador"]]),
            "erros_graves": _contagem(analise)["erro_grave"],
        })
    evolucao.sort(key=lambda x: x["data"] or "")
    rating = round(sum(ratings[:10]) / len(ratings[:10])) if ratings else 1200

    puzzles: list[dict] = []
    for tema, _ in temas.most_common(3):
        try:
            achados = await mcp_cliente.chamar("buscar_puzzles", {
                "temas": [tema], "rating_min": rating - 200, "rating_max": rating + 200,
                "quantidade": puzzles_por_tema})
        except mcp_cliente.ErroFerramenta as e:
            log.warning("buscar_puzzles falhou: %s", e)
            break
        vistos = {pz["id"] for pz in puzzles}
        puzzles += [{**pz, "tema_recomendado": tema} for pz in achados if pz["id"] not in vistos]

    return {
        "usuario": usuario,
        "partidas_analisadas": len(evolucao),
        "rating_estimado": rating,
        "temas_fracos": [{"tema": t, "tema_label": rotulo(t), "erros": n} for t, n in temas.most_common()],
        "evolucao": evolucao,
        "puzzles_recomendados": puzzles,
    }


# --------------------------------------------------------------------------- #
# Tarefa em segundo plano
# --------------------------------------------------------------------------- #

async def _rodar_analise(tarefa_id: str, partida: dict[str, Any]) -> None:
    db.atualizar_tarefa(tarefa_id, status="em_andamento", etapa="analisando")

    async def progresso(feito: float, total: float | None, _mensagem: str | None) -> None:
        db.atualizar_tarefa(tarefa_id, lance_atual=int(feito), total_lances=int(total or 0))

    try:
        lances = await mcp_cliente.chamar(
            "analisar_partida", {"pgn": partida["pgn"], "cor_do_jogador": partida["cor_do_jogador"]},
            progresso=progresso)
        db.salvar_analise(partida["id"], lances)

        db.atualizar_tarefa(tarefa_id, etapa="explicando")
        for i, l in enumerate(lances):
            if not (l["do_jogador"] and l["classe"] in CLASSES_EXPLICADAS):
                continue
            if db.obter_explicacao(l["fen_antes"], l["uci"]):
                continue
            proximo = lances[i + 1] if i + 1 < len(lances) else None
            ctx = {
                "fen_antes": l["fen_antes"], "fen_depois": l["fen_depois"],
                "lance_jogado": l["san"], "melhor_lance": l["melhor_lance"], "linha_motor": l["linha_motor"],
                # melhor resposta do adversário = melhor lance da posição seguinte
                "melhor_resposta": proximo["melhor_lance"] if proximo else None,
                "chance_antes": l["chance_vitoria_antes"], "chance_depois": l["chance_vitoria_depois"],
                "queda": l["queda"], "classe": l["classe"], "cor": l["cor"],
            }
            try:
                db.salvar_explicacao(l["fen_antes"], l["uci"], await agente.explicar_erro(ctx))
            except Exception as e:  # noqa: BLE001 - uma explicação falha não derruba a análise
                log.exception("Falha ao explicar %s: %s", l["san"], e)

        db.atualizar_tarefa(tarefa_id, status="concluida", etapa=None)
    except mcp_cliente.ErroFerramenta as e:
        db.atualizar_tarefa(tarefa_id, status="erro", erro=str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("Erro inesperado na análise")
        db.atualizar_tarefa(tarefa_id, status="erro", erro=f"Erro inesperado: {e}")
