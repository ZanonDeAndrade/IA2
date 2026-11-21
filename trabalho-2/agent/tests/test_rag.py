import os
from pathlib import Path

import pytest

from knowledge_base import index
from mcp_server.tools.concepts import buscar_conceitos


@pytest.fixture
def indice(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    return tmp_path


def test_indice_busca_filtros_e_reindexacao(indice, monkeypatch):
    chamadas = []

    def vetores(textos, modelo):
        chamadas.append(textos)
        return [[1.0, 0.0] if "cavalo" in texto.lower() else [0.0, 1.0] for texto in textos]

    monkeypatch.setattr(index, "vetorizar", vetores)
    assert buscar_conceitos("cavalo") == []
    for id_, titulo, tema in (("garfo", "Cavalo", "fork"), ("mate", "Mate", "mate")):
        (indice / f"{id_}.md").write_text(
            f"---\nid: {id_}\ntitulo: {titulo}\ntema: {tema}\ntema_pt: {id_}\nnivel: iniciante\n---\n"
            "## Definição\n\nTexto.\n", encoding="utf-8",
        )
    assert index.indexar(indice) == 2
    assert index.indexar(indice) == 2
    assert len(chamadas) == 1
    resultados = buscar_conceitos("cavalo")
    assert [r["id"] for r in resultados] == ["garfo", "mate"]
    assert resultados[0]["arquivo"] == "knowledge_base/garfo.md"
    assert resultados[0]["nivel"] == "iniciante"
    assert buscar_conceitos("cavalo", tema="mate")[0]["id"] == "mate"
    assert buscar_conceitos("cavalo", k=1, tema="fork")[0]["id"] == "garfo"
    assert buscar_conceitos("cavalo", tema="garfo")[0]["id"] == "garfo"
    assert buscar_conceitos("cavalo", tema="inexistente") == []
    antes = len(chamadas)
    assert index.indexar(indice, reconstruir=True) == 2
    assert len(chamadas) == antes + 1
    for ficha in indice.glob("*.md"):
        ficha.unlink()
    assert index.indexar(indice) == 0
    assert buscar_conceitos("cavalo") == []


def test_divide_fichas_longas_por_subtitulo(tmp_path):
    (tmp_path / "longa.md").write_text(
        "---\nid: longa\ntitulo: Ficha longa\ntema_pt: longa\ntema: fork\nnivel: iniciante\n---\n"
        "## Primeiro\n" + "palavra " * 500 + "\n## Segundo\nSeção final.",
        encoding="utf-8",
    )
    trechos = index.carregar_trechos(tmp_path)
    assert list(trechos) == ["longa:0", "longa:1"]
    assert trechos["longa:1"][0].startswith("## Segundo")


@pytest.mark.skipif(os.environ.get("LANCE_TESTE_EMBEDDINGS") != "1", reason="requer o modelo de embeddings")
def test_recuperacao_semantica_multilingue(indice):
    assert index.indexar() >= 30
    resultados = buscar_conceitos("How does a knight fork two pieces at once?")
    assert len(resultados) == 4
    assert "garfo" in {r["id"] for r in resultados}
