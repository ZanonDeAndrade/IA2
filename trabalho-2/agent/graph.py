"""Fluxos do agente em LangGraph, com as ferramentas MCP carregadas por
``langchain-mcp-adapters``.

Modo 1 (fluxo fixo): explicar um erro.
    1. Recebe a posição antes do erro, o lance jogado, o melhor lance e a linha
       do motor.
    2. Chama ``descrever_posicao`` antes e depois do lance.
    3. Pede ao LLM o tema tático, de uma lista fechada.
    4. Chama ``buscar_conceitos`` com o tema e recupera a ficha.
    5. O LLM redige a explicação.
    6. O validador confere todos os lances citados (``agent/validator.py``).
    7. Em caso de falha, o LLM refaz (no máximo 2 tentativas); depois disso, a
       resposta é uma explicação-padrão montada só com os dados do motor.

Modo 2 (agente livre, estilo ReAct): chat sobre a posição.
    A cada pergunta o agente recebe o FEN da tela, decide quais ferramentas
    chamar e a resposta final passa pelo mesmo validador do modo 1.

Em nenhum dos modos um texto chega ao usuário sem passar pelo validador.
"""

MAX_TENTATIVAS = 2


def carregar_ferramentas_mcp() -> list:
    """Conecta ao servidor MCP e devolve as ferramentas como tools do LangChain.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def construir_grafo_explicacao():
    """Monta o grafo do modo 1 (explicar um erro) e devolve o grafo compilado.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def construir_agente_chat():
    """Monta o agente do modo 2 (chat sobre a posição) e devolve o grafo compilado.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def explicar_erro(
    fen: str,
    lance_jogado: str,
    melhor_lance: str,
    linha_motor: list[str],
) -> dict:
    """Executa o modo 1 para um erro específico.

    Args:
        fen: posição antes do lance jogado.
        lance_jogado: lance do jogador em SAN.
        melhor_lance: melhor lance segundo o motor, em SAN.
        linha_motor: linha principal do motor a partir do melhor lance.

    Returns:
        dict com ``tema``, ``texto``, ``ficha`` (fonte do RAG),
        ``ferramentas_usadas``, ``tentativas`` e ``validada``.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError


def responder_chat(fen: str, pergunta: str, historico: list[dict] | None = None) -> dict:
    """Executa o modo 2 para uma pergunta sobre a posição exibida.

    Args:
        fen: posição atual no tabuleiro.
        pergunta: pergunta do usuário.
        historico: mensagens anteriores da conversa, se houver.

    Returns:
        dict com ``resposta``, ``ferramentas_usadas`` e ``validada``.

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError
