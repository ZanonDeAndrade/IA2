"""Validador das respostas do agente: nenhum lance inventado chega à tela.

Extrai todos os lances citados no texto gerado pelo LLM e confere cada um com a
ferramenta ``validar_lances`` (legalidade na posição) e com a linha do motor
(coerência com a recomendação). Se algo falhar, o fluxo devolve o erro ao LLM
para uma nova tentativa (ver ``agent/graph.py``).
"""


def extrair_lances(texto: str) -> list[str]:
    """Extrai os lances em notação algébrica (SAN) citados em um texto.

    Args:
        texto: resposta gerada pelo LLM.

    Returns:
        Lista de lances encontrados, na ordem em que aparecem.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def validar_resposta(texto: str, fen: str, linha_motor: list[str] | None = None) -> dict:
    """Confere os lances citados em uma resposta do agente.

    Args:
        texto: resposta gerada pelo LLM.
        fen: posição de referência para a validação.
        linha_motor: linha principal do motor, usada para checar se o lance
            recomendado bate com o do Stockfish (opcional).

    Returns:
        dict com ``valida`` (bool), ``lances`` (resultado de ``validar_lances``
        por lance) e ``erros`` (mensagens a devolver ao LLM, se houver).

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def explicacao_padrao(lance_jogado: str, melhor_lance: str, linha_motor: list[str]) -> str:
    """Monta a explicação-padrão usada após esgotar as tentativas do LLM.

    Usa só os dados do motor (lance jogado, melhor lance e linha principal),
    sem texto gerado.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError
