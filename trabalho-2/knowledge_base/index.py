"""Indexação opcionalmente reconstruível das fichas Markdown no ChromaDB."""

import argparse
from functools import lru_cache
from hashlib import sha256
import os
from pathlib import Path
import re

import chromadb
import yaml
from chromadb.errors import NotFoundError

PASTA_FICHAS = Path(__file__).resolve().parent
MODELO_PADRAO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_SUBTITULO = re.compile(r"(?=^#{2,6} +)", re.MULTILINE)
_CAMPOS = ("id", "titulo", "tema", "tema_pt", "nivel")
_VERSAO_INDICE = "2"


@lru_cache(maxsize=1)
def _modelo(nome: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(nome, device="cpu")


def vetorizar(textos: list[str], modelo: str) -> list[list[float]]:
    return _modelo(modelo).encode(textos, normalize_embeddings=True).tolist()


def _config() -> tuple[Path, str, str]:
    caminho = Path(os.environ.get("CHROMA_PATH") or PASTA_FICHAS.parent / "data" / "chroma")
    modelo = os.environ.get("EMBEDDING_MODEL") or MODELO_PADRAO
    nome = "conceitos-" + sha256(f"{_VERSAO_INDICE}:{modelo}".encode()).hexdigest()[:16]
    return caminho, modelo, nome


def carregar_trechos(pasta: Path) -> dict[str, tuple[str, dict[str, str]]]:
    trechos = {}
    fichas = set()
    for arquivo in sorted(pasta.glob("*.md")):
        if arquivo.name == "README.md":
            continue
        partes = arquivo.read_text(encoding="utf-8").split("---", 2)
        if len(partes) != 3 or partes[0].strip():
            raise ValueError(f"Metadados ausentes em {arquivo.name}")
        documento = partes[2].strip()
        dados = yaml.safe_load(partes[1])
        if not isinstance(dados, dict) or any(
            not isinstance(dados.get(campo), str) or not dados[campo].strip() for campo in _CAMPOS
        ) or not documento:
            raise ValueError(f"Ficha inválida: {arquivo.name}")
        if dados["id"] in fichas:
            raise ValueError(f"Identificador duplicado: {dados['id']}")
        fichas.add(dados["id"])
        metadados = {campo: dados[campo] for campo in _CAMPOS}
        metadados["arquivo"] = f"knowledge_base/{arquivo.name}"
        secoes = _SUBTITULO.split(documento) if len(documento.split()) > 500 else [documento]
        for indice, secao in enumerate(s for s in secoes if s.strip()):
            trechos[f"{dados['id']}:{indice}"] = (secao.strip(), metadados)
    return trechos


def indexar(pasta: Path = PASTA_FICHAS, *, reconstruir: bool = False) -> int:
    """Atualiza apenas trechos alterados e remove os que saíram da base."""
    trechos = carregar_trechos(pasta)
    caminho, modelo, nome = _config()
    cliente = chromadb.PersistentClient(path=str(caminho))
    colecao = cliente.get_or_create_collection(nome, embedding_function=None)
    antigos = colecao.get(include=["metadatas"])
    hashes = {id_: meta["hash"] for id_, meta in zip(antigos["ids"], antigos["metadatas"] or [])}
    ids, documentos, metadados = [], [], []
    for id_, (texto, meta) in trechos.items():
        digest = sha256(repr((texto, meta)).encode()).hexdigest()
        if reconstruir or hashes.get(id_) != digest:
            ids.append(id_)
            documentos.append(texto)
            metadados.append({**meta, "hash": digest})
    if ids:
        # Preserva a ficha completa no índice. Referências e FENs não orientam a similaridade.
        textos_busca = []
        for meta, texto in zip(metadados, documentos):
            conteudo = texto.split("## Referências", 1)[0].strip()
            conteudo = re.sub(r"^(?:FEN|Lances):.*$", "", conteudo, flags=re.MULTILINE)
            textos_busca.append(f"{meta['titulo']} ({meta['tema']})\n{conteudo}")
        vetores = vetorizar(
            textos_busca, modelo,
        )
        colecao.upsert(ids=ids, documents=documentos, metadatas=metadados, embeddings=vetores)
    removidos = list(hashes.keys() - trechos.keys())
    if removidos:
        colecao.delete(ids=removidos)
    return len(trechos)


def recuperar(pergunta: str, k: int = 4, tema: str | None = None) -> list[dict]:
    if k <= 0:
        raise ValueError("k deve ser positivo.")
    if not pergunta.strip():
        return []
    caminho, modelo, nome = _config()
    if not caminho.is_dir():
        return []
    cliente = chromadb.PersistentClient(path=str(caminho))
    try:
        colecao = cliente.get_collection(nome, embedding_function=None)
    except NotFoundError:
        return []
    quantidade = colecao.count()
    if quantidade == 0:
        return []
    filtro = {"$or": [{"tema": tema}, {"tema_pt": tema}]} if tema else None
    resultado = colecao.query(
        query_embeddings=vetorizar([pergunta], modelo),
        n_results=min(k, quantidade), where=filtro, include=["documents", "metadatas"],
    )
    return [
        {**{chave: meta[chave] for chave in (*_CAMPOS, "arquivo")}, "texto": texto, "trecho_id": id_}
        for id_, texto, meta in zip(resultado["ids"][0], resultado["documents"][0], resultado["metadatas"][0])
    ]


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(PASTA_FICHAS.parent / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reconstruir", action="store_true")
    argumentos = parser.parse_args()
    print(f"{indexar(reconstruir=argumentos.reconstruir)} trechos ativos.")
