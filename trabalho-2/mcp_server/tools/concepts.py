"""Busca semântica nas fichas de xadrez indexadas no ChromaDB."""

import os
from pathlib import Path


def buscar_conceitos(pergunta: str, k: int = 4, tema: str | None = None) -> list[dict]:
    """Recupera até k trechos com fonte. Tema aceita o identificador da ficha ou da Lichess."""
    if k <= 0:
        raise ValueError("k deve ser positivo.")
    if not pergunta.strip():
        return []
    caminho = Path(os.getenv("CHROMA_PATH") or Path(__file__).resolve().parents[2] / "data" / "chroma")
    if not caminho.is_dir():
        # O perfil mínimo e a primeira execução não precisam importar Chroma
        # (nem suas dependências nativas) enquanto não houver índice.
        return []
    from knowledge_base.index import recuperar

    return recuperar(pergunta, k, tema)
