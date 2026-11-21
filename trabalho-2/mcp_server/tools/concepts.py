"""Busca semântica nas fichas de xadrez indexadas no ChromaDB."""


def buscar_conceitos(pergunta: str, k: int = 4, tema: str | None = None) -> list[dict]:
    """Recupera até k trechos com fonte. Tema aceita o identificador da ficha ou da Lichess."""
    from knowledge_base.index import recuperar

    return recuperar(pergunta, k, tema)
