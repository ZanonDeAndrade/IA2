"""Roda a avaliação das três versões do explicador e salva os resultados.

Placeholder. Experimento previsto (ver documentação, seção 10):

Conjunto de teste (``evaluation/dataset.jsonl``, 100 posições):
    70 da base de puzzles da Lichess (primeiro lance da solução = erro do
    adversário, tema já rotulado) e 30 de partidas reais rotuladas pelo grupo.
    Campos: ``fen``, ``lance_jogado``, ``melhor_lance``, ``tema_esperado``, ``origem``.

Versões comparadas:
    A – LLM puro: só o FEN e o lance jogado.
    B – LLM + motor no prompt: saída do Stockfish colada no prompt, sem
        ferramentas nem validador.
    C – Agente completo: fluxo do modo 1 (ferramentas MCP, RAG e validador).

Métricas por versão:
    lances inválidos citados (%), acerto do melhor lance (%), acerto do tema (%),
    qualidade percebida (1 a 5, avaliação cega), fidelidade do RAG (RAGAS),
    custo (tokens) e tempo (s) por explicação.

Saída: CSV e gráficos em ``evaluation/results/``.

Uso (a partir de ``trabalho-2/``):
    python evaluation/run_eval.py --versoes A B C --dataset evaluation/dataset.jsonl
"""

VERSOES = ("A", "B", "C")
CAMINHO_DATASET_PADRAO = "evaluation/dataset.jsonl"
PASTA_RESULTADOS = "evaluation/results"


def carregar_dataset(caminho: str = CAMINHO_DATASET_PADRAO) -> list[dict]:
    """Lê o ``dataset.jsonl`` e devolve a lista de posições de teste.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def rodar_versao(versao: str, dataset: list[dict]) -> list[dict]:
    """Gera uma explicação por posição com a versão indicada (``A``, ``B`` ou ``C``).

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def calcular_metricas(resultados: list[dict]) -> dict:
    """Calcula as métricas de uma versão a partir das explicações geradas.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def salvar_resultados(metricas_por_versao: dict, pasta: str = PASTA_RESULTADOS) -> None:
    """Salva a tabela (CSV) e o gráfico de barras comparando as versões.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def main() -> None:
    """Lê os argumentos da linha de comando e executa a avaliação completa.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


if __name__ == "__main__":
    main()
