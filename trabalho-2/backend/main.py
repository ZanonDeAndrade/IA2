"""API do Lance a Lance (FastAPI).

Endpoints consumidos pela interface. A análise de uma partida roda em segundo
plano (``BackgroundTasks``) e a interface consulta o progresso a cada 2 s.
Todas as rotas devolvem **501 Not Implemented** até serem implementadas.

Execução (a partir de ``trabalho-2/``):
    uvicorn backend.main:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException, status

app = FastAPI(
    title="Lance a Lance API",
    description="Treinador de xadrez com IA: análise de partidas, explicações e relatórios.",
    version="0.1.0",
)


def _nao_implementado() -> None:
    """Interrompe a requisição com 501 Not Implemented."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Endpoint ainda não implementado.",
    )


@app.post("/api/partidas/importar", status_code=status.HTTP_201_CREATED)
def importar_partidas() -> dict:
    """Busca as partidas de um usuário do Chess.com ou recebe um PGN colado.

    Corpo esperado: ``{"usuario": str, "max": int}`` ou ``{"pgn": str}``.
    Resposta: lista de partidas importadas (ver ``frontend/src/mocks/partidas.json``).
    """
    _nao_implementado()


@app.post("/api/partidas/{id}/analisar", status_code=status.HTTP_202_ACCEPTED)
def analisar_partida(id: str) -> dict:
    """Inicia a análise da partida em segundo plano e devolve o id da tarefa.

    Resposta: ``{"tarefa_id": str}`` (ver ``frontend/src/mocks/tarefa.json``).
    """
    _nao_implementado()


@app.get("/api/partidas/{id}")
def obter_partida(id: str) -> dict:
    """Devolve a partida com lances, avaliações, classes e explicações prontas.

    Ver ``frontend/src/mocks/partida.json``.
    """
    _nao_implementado()


@app.get("/api/tarefas/{id}")
def obter_tarefa(id: str) -> dict:
    """Devolve o progresso de uma análise (para a barra de carregamento).

    Ver ``frontend/src/mocks/tarefa.json``.
    """
    _nao_implementado()


@app.post("/api/explicar")
def explicar() -> dict:
    """Explica um lance específico (FEN + lance), via modo 1 do agente.

    Corpo esperado: ``{"fen": str, "lance_jogado": str}``.
    Ver ``frontend/src/mocks/explicacao.json``.
    """
    _nao_implementado()


@app.post("/api/chat")
def chat() -> dict:
    """Responde a uma pergunta sobre a posição atual, via modo 2 do agente.

    Corpo esperado: ``{"fen": str, "pergunta": str, "historico": list}``.
    Resposta inclui as ferramentas usadas (ver ``frontend/src/mocks/chat.json``).
    """
    _nao_implementado()


@app.get("/api/relatorio/{usuario}")
def obter_relatorio(usuario: str) -> dict:
    """Devolve os temas fracos somados e os puzzles recomendados do usuário.

    Ver ``frontend/src/mocks/relatorio.json``.
    """
    _nao_implementado()
