"""Ferramenta de RAG: busca nas fichas de conceitos indexadas no ChromaDB.

As fichas vivem em ``knowledge_base/`` (uma por tema, em Markdown, com
metadados ``tema`` e ``nivel``). Cada ficha vira um trecho; fichas com mais de
~500 palavras são divididas por subtítulo.
"""


def buscar_conceitos(pergunta: str, k: int = 4) -> list[dict]:
    """Recupera os trechos de fichas mais semelhantes à pergunta.

    Args:
        pergunta: texto da consulta (tema tático ou pergunta do usuário).
        k: quantidade de trechos devolvidos (padrão 4). Quando o tema já é
            conhecido, a busca pode ser filtrada por ele.

    Returns:
        Lista de trechos, cada um com ``titulo``, ``tema``, ``nivel``, ``texto``
        e ``arquivo`` (caminho da ficha, mostrado na interface como fonte).

    Raises:
        NotImplementedError: ainda não implementado.
    """
    raise NotImplementedError
