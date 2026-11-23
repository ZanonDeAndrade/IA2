"""Rotas HTTP do modo jogar contra o Stockfish."""

import asyncio
from contextlib import closing
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Path, Query, Request, Response

from backend import db, services
from backend.jogo import repositorio, servico, treinador
from backend.jogo.modelos import (
    AlterarConfiguracoes, AvaliacaoPosicao, ChatJogo, Dica, EstadoJogo, ExplicacaoJogo, HistoricoJogo, IniciarJogo,
    JogarLance, Metricas, PainelTreinador, PartidasDaSessao, PedidoDica, PedidoExplicacao, PerguntaJogo, ReivindicarEmpate,
    RelatorioJogo, ResultadoJogo, StatusTreinador, Versao,
)
from backend.schemas import Erro, Explicacao
from mcp_server.tools.engine import perfil_analise
from mcp_server.tools.pgn import LIMITE_MEIOS_LANCES

Id = Annotated[str, Path(min_length=1, max_length=100)]
Indice = Annotated[int, Path(ge=1, le=LIMITE_MEIOS_LANCES)]
_SESSAO = Header(alias="X-Sessao-Jogo", pattern=r"^[0-9a-f]{64}$")
_FALHAS_MOTOR = {504: {"model": Erro, "description": "Prazo de processamento excedido"}}
router = APIRouter(prefix="/api/jogo", tags=["Jogar contra IA"], responses={
    404: {"model": Erro, "description": "Partida ou lance não encontrado"},
    409: {"model": Erro, "description": "Conflito de versão, processamento ou estado"},
})
router_treinador = APIRouter(prefix="/api/treinador", tags=["Treinador"])


def pos_turno(estado: EstadoJogo, request: Request, tarefas: BackgroundTasks) -> EstadoJogo:
    """Agenda a revisão completa quando o turno encerra a partida."""
    if estado.status == "encerrada" and estado.partida_analise_id:
        assinatura = perfil_analise()
        with closing(db.conectar()) as conn:
            try:
                tarefa, criar = db.iniciar_tarefa(conn, estado.partida_analise_id, assinatura)
            except (KeyError, OverflowError):
                criar = False
            if criar:
                partida = db.obter_partida(conn, estado.partida_analise_id)
                tarefas.add_task(services.analisar_em_segundo_plano, tarefa, partida, assinatura,
                                 request.app.state.fila_motor)
    return estado


@router.post("/iniciar", status_code=201, response_model=EstadoJogo, responses=_FALHAS_MOTOR)
async def iniciar(entrada: IniciarJogo, sessao: Annotated[str | None, _SESSAO] = None) -> EstadoJogo:
    """Cria a partida e executa o primeiro lance do Stockfish se o jogador for de pretas."""
    return await servico.iniciar(entrada, sessao)


@router.get("/partidas", response_model=PartidasDaSessao)
def listar_partidas(
    resposta: Response,
    sessao: Annotated[str, _SESSAO],
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
    deslocamento: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> PartidasDaSessao:
    """Lista os jogos iniciados nesta sessão, do mais recente ao mais antigo."""
    resposta.headers["Cache-Control"] = "no-store"
    return PartidasDaSessao(partidas=repositorio.listar(sessao, limite, deslocamento))


@router.get("/{id}/treinador", response_model=PainelTreinador)
async def painel_treinador(id: Id) -> dict:
    """Explicações e dicas da partida, cada uma vinculada ao seu lance ou versão."""
    jogo, _ = repositorio.obter(id)
    return {"jogo_id": id, "versao": jogo.versao, "modo_assistencia": jogo.configuracoes.modo_assistencia,
            "treinador": await treinador.status_llm(), "explicacoes": treinador.listar(id),
            "dicas": treinador._dicas(id), "fila": treinador.resumo_fila()}


@router.post("/{id}/explicacoes/{indice}", status_code=202, response_model=ExplicacaoJogo)
async def pedir_explicacao(id: Id, indice: Indice, entrada: PedidoExplicacao | None = None) -> dict:
    """Enfileira a explicação de um lance. Reaproveita a salva, exceto com ``forcar``."""
    jogo, _ = repositorio.obter(id)
    if not jogo.configuracoes.modo_treinador:
        raise HTTPException(409, "O modo treinador está desativado nesta partida.")
    lance = servico.lance_do_jogador(jogo, indice)
    return treinador.enfileirar(jogo, lance, forcar=bool(entrada and entrada.forcar))


@router.post("/{id}/explicacoes/{indice}/cancelar", response_model=ExplicacaoJogo)
async def cancelar_explicacao(id: Id, indice: Indice) -> dict:
    repositorio.obter(id)
    return treinador.cancelar(id, indice)


@router.post("/{id}/dica", response_model=Dica, responses=_FALHAS_MOTOR)
async def pedir_dica(id: Id, entrada: PedidoDica) -> dict:
    """Dica em etapas: objetivo, peça ou casa e, só no nível 3, o lance do Stockfish."""
    return await treinador.dica(id, entrada.versao, entrada.nivel)


@router.post("/{id}/chat", response_model=ChatJogo, responses={504: {"model": Erro}})
async def conversar(id: Id, entrada: PerguntaJogo, request: Request) -> dict:
    return await treinador.chat(id, entrada, request.app.state.fila_llm)


@router.get("/{id}/relatorio", response_model=RelatorioJogo)
async def relatorio_jogo(id: Id) -> dict:
    return await treinador.relatorio(id)


@router.post("/{id}/configuracoes", response_model=EstadoJogo)
def configurar(id: Id, entrada: AlterarConfiguracoes) -> EstadoJogo:
    """Altera o modo de assistência e as preferências; vale a partir do próximo lance."""
    return servico.configurar(id, entrada.versao, entrada.model_dump(exclude={"versao"}))


@router_treinador.get("/status", response_model=StatusTreinador)
async def status_treinador() -> StatusTreinador:
    return await treinador.status_llm(renovar=True)


@router_treinador.get("/metricas", response_model=Metricas)
def metricas_treinador() -> dict:
    return treinador.metricas()


@router.get("/{id}", response_model=EstadoJogo)
def obter(id: Id) -> EstadoJogo:
    return servico.estado(*repositorio.obter(id))


@router.get("/{id}/posicao", response_model=AvaliacaoPosicao, responses=_FALHAS_MOTOR)
async def posicao(id: Id, versao: Annotated[int, Query(ge=0)], recomendar: bool = False) -> AvaliacaoPosicao:
    """Avalia a posição atual, com o melhor lance somente quando solicitado."""
    return await servico.avaliar_posicao(id, versao, recomendar)


@router.get("/{id}/historico", response_model=HistoricoJogo)
def historico(id: Id) -> HistoricoJogo:
    jogo, _ = repositorio.obter(id)
    return HistoricoJogo(id=jogo.id, versao=jogo.versao, lances=jogo.lances)


@router.post("/{id}/mover", response_model=EstadoJogo, responses=_FALHAS_MOTOR)
async def mover(id: Id, entrada: JogarLance, request: Request, tarefas: BackgroundTasks) -> EstadoJogo:
    """Confirma a jogada humana e, em uma única atualização, a resposta do motor.

    A classificação volta nesta resposta. A explicação é gerada depois, pela fila do treinador.
    """
    estado = await servico.mover(id, entrada.versao, entrada.lance, agendar=treinador.agendar_automatico)
    treinador.acordar_fila()
    return pos_turno(estado, request, tarefas)


@router.post("/{id}/desistir", response_model=EstadoJogo)
def desistir(id: Id, entrada: Versao, request: Request, tarefas: BackgroundTasks) -> EstadoJogo:
    return pos_turno(servico.desistir(id, entrada.versao), request, tarefas)


@router.post("/{id}/reivindicar-empate", response_model=EstadoJogo)
def reivindicar(id: Id, entrada: ReivindicarEmpate, request: Request, tarefas: BackgroundTasks) -> EstadoJogo:
    """Reivindica empate na posição atual ou declara uma jogada que permite reivindicá-lo."""
    return pos_turno(servico.reivindicar(id, entrada.versao, entrada.lance), request, tarefas)


@router.get("/{id}/resultado", response_model=ResultadoJogo)
def resultado(id: Id) -> ResultadoJogo:
    jogo, _ = repositorio.obter(id)
    if jogo.motivo is None:
        raise HTTPException(409, "A partida ainda está em andamento.")
    return ResultadoJogo(id=jogo.id, resultado=jogo.resultado, motivo=jogo.motivo, pgn=jogo.pgn,
                         partida_analise_id=jogo.partida_analise_id, estatisticas=servico.estatisticas(jogo))


@router.post("/{id}/historico/{indice}/avaliar", response_model=EstadoJogo, responses=_FALHAS_MOTOR)
async def avaliar(id: Id, indice: Indice, entrada: Versao) -> EstadoJogo:
    return await servico.avaliar_indice(id, entrada.versao, indice)


@router.post("/{id}/historico/{indice}/explicar", response_model=Explicacao, responses=_FALHAS_MOTOR)
async def explicar(id: Id, indice: Indice, request: Request) -> dict:
    jogo, _ = repositorio.obter(id)
    if not jogo.configuracoes.modo_treinador:
        raise HTTPException(409, "O modo treinador está desativado nesta partida.")
    lance = servico.lance_do_jogador(jogo, indice)
    if lance.avaliacao is None:
        raise HTTPException(409, "Avalie o lance antes de solicitar a explicação.")
    try:
        return await asyncio.wait_for(services.explicacao(lance.fen_antes, lance.san, request.app.state.fila_llm,
                                                         analise=lance.avaliacao.model_dump()), 150)
    except TimeoutError as erro:
        raise HTTPException(504, "O prazo da explicação foi excedido.") from erro
