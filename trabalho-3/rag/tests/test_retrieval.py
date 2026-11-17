import json
import os
import subprocess
import sys

import pytest

from rag.ingest import ingest
from rag.retrieve import InvalidQuery, Retriever
from rag.vector_store import index_metadata


@pytest.fixture(scope="module")
def indexed(tmp_path_factory, pdf_corpus):
    directory = tmp_path_factory.mktemp("rag")
    chroma = directory / "chroma"
    recipes = directory / "recipes.json"
    offline = os.environ.get("HF_HUB_OFFLINE") == "1"
    report = ingest(pdf_corpus, chroma, recipes, offline=offline)
    return Retriever(chroma, recipes, offline=offline), chroma, recipes, report


def test_ingestion_is_idempotent_and_persists_across_processes(indexed, pdf_corpus):
    retriever, chroma, recipes, first = indexed
    before = retriever.collection.get(include=[])["ids"]
    again = ingest(pdf_corpus, chroma, recipes, offline=True)
    assert again["reused"] and not first["reused"]
    assert again["collection"] == first["collection"]
    assert again["vectors"] == first["vectors"] == len(set(before))
    assert retriever.collection.get(include=[])["ids"] == before
    sample = retriever.collection.get(ids=before[:1], include=["embeddings"])
    assert sample["embeddings"].shape == (1, 384)
    store_result = subprocess.check_output([
        sys.executable, "-m", "rag.retrieve", "--topics",
        "--chroma-path", str(chroma), "--recipes", str(recipes), "--offline",
    ], text=True)
    assert json.loads(store_result)["total_topics"] == 2
    assert retriever.collection.metadata["corpus_sha256"] == index_metadata(recipes.read_bytes())["corpus_sha256"]


def test_search_and_lookup_cite_original_pdf_page(indexed):
    retriever = indexed[0]
    result = retriever.search("Como fazer bolo de cenoura?", include_trace=True)
    assert result["evidence_status"] == "FOUND"
    assert result["retrieved_count"] <= 8
    hit = result["results"][0]
    assert hit["source_url"] == "data/raw/Massas%20e%20bolos.PDF#page=3"
    assert hit["page"] == 3
    page = retriever.get_document(hit["recipe_id"])["recipe"]
    assert hit["source_url"] == page["source_url"]
    assert hit["source_excerpt"] in page["text"]
    assert retriever.get_document("inventada")["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert retriever.search("Como consertar um motor de foguete?")["evidence_status"] == "INSUFFICIENT"


def test_ingredients_are_mentions_and_topic_filters_pdf(indexed):
    retriever = indexed[0]
    result = retriever.search("O que posso fazer com ovos e queijo?", topic_key="ovos")
    assert result["evidence_status"] == "FOUND"
    assert result["results"][0]["mentioned_ingredients"] == ["ovos", "queijo"]
    assert result["results"][0]["compatibility"] is None
    assert result["results"][0]["source_filename"] == "Ovos.pdf"
    assert retriever.search("Omelete", topic_key="massas-e-bolos")["evidence_status"] == "INSUFFICIENT"


def test_empty_index_and_invalid_arguments(tmp_path):
    with pytest.raises(ValueError, match="Nenhum PDF"):
        ingest(tmp_path, tmp_path / "chroma", tmp_path / "recipes.json", offline=True)
    retriever = Retriever(tmp_path / "chroma", tmp_path / "recipes.json", offline=True)
    assert retriever.search("Procuro panqueca")["error"]["code"] == "CORPUS_EMPTY"
    assert retriever.list_topics() == {"topics": [], "total_topics": 0, "corpus_ready": False}
    with pytest.raises(InvalidQuery):
        retriever.search("Panqueca", top_k=0)
    with pytest.raises(InvalidQuery):
        retriever.search("Panqueca", topic_key=0)
    with pytest.raises(InvalidQuery):
        retriever.search("Panqueca", available_ingredients=[" "])


def test_rejects_invalid_candidate_provenance(indexed):
    retriever = indexed[0]
    sample = retriever.collection.get(limit=1, include=["documents", "metadatas"])
    text, metadata = sample["documents"][0], sample["metadatas"][0]
    assert retriever._valid_candidate(text, metadata, 0.2)
    assert not retriever._valid_candidate(text, {**metadata, "source_url": ""}, 0.2)
    assert not retriever._valid_candidate(text, {**metadata, "recipe_id": "inventada"}, 0.2)
    assert not retriever._valid_candidate(text + " adulterado", metadata, 0.2)


def test_corrupt_snapshot_cannot_replace_a_valid_publication(indexed, tmp_path):
    retriever, chroma, recipes, first = indexed
    damaged_data = tmp_path / "damaged"
    (damaged_data / "raw").mkdir(parents=True)
    snapshot = damaged_data / "raw" / "danificado.pdf"
    snapshot.write_bytes(b"corrompido")
    corpus_before = recipes.read_bytes()
    with pytest.raises(ValueError, match=r"danificado\.pdf:"):
        ingest(damaged_data, chroma, recipes, offline=True)
    assert recipes.read_bytes() == corpus_before
    assert retriever.collection.count() == first["vectors"]
