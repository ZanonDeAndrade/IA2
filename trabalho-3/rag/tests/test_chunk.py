import os
import re
from unicodedata import normalize

import pytest

from rag.chunk import CHUNK_OVERLAP, CHUNK_SIZE, build_chunks, split_text, token_count
from rag.embed import DIMENSION, Embedder
from rag.extract import read_pdf
from rag.ingest import load_pages


@pytest.fixture(scope="module")
def embedder():
    return Embedder(offline=os.environ.get("HF_HUB_OFFLINE") == "1")


def test_pdfs_keep_physical_page_numbers_and_ignore_html(pdf_corpus):
    sources, pages = load_pages(pdf_corpus)
    assert len(sources) == 2
    assert sources[0]["pages"] == 3
    assert sources[0]["pages_without_text"] == [2]
    assert [page["page"] for page in pages] == [1, 3, 1]
    assert pages[1]["source_url"] == "data/raw/Massas%20e%20bolos.PDF#page=3"
    assert "Bolo de cenoura" in pages[1]["text"]


def test_pdf_id_survives_unicode_filename_normalization(pdf_corpus, tmp_path):
    pdf = (pdf_corpus / "raw" / "Ovos.pdf").read_bytes()
    sources = []
    for form in ("NFC", "NFD"):
        directory = tmp_path / form
        directory.mkdir()
        path = directory / normalize(form, "Receitas da Vovó.pdf")
        path.write_bytes(pdf)
        source, _ = read_pdf(path)
        sources.append(source)
    assert sources[0]["document_id"] == sources[1]["document_id"]


def test_pdf_chunks_use_real_tokenizer_and_carry_page_provenance(embedder, pdf_corpus):
    _, pages = load_pages(pdf_corpus)
    for page in pages:
        chunks = build_chunks(page, embedder.tokenizer)
        assert all(c.metadata["page"] == page["page"] for c in chunks)
        assert all(c.metadata["source_url"] == page["source_url"] for c in chunks)
        assert all(token_count(embedder.tokenizer, c.text) <= CHUNK_SIZE for c in chunks)
        assert chunks == build_chunks(page, embedder.tokenizer)


def test_overlap_has_expected_size(embedder):
    text = " ".join([f"ovo leite sal farinha porção {number}" for number in range(40)])
    chunks = list(split_text(text, embedder.tokenizer))
    first, second = [embedder.tokenizer(chunk, add_special_tokens=False)["input_ids"] for chunk in chunks[:2]]
    assert len(chunks) > 2
    overlap = max(size for size in range(1, len(first)) if first[-size:] == second[:size])
    assert CHUNK_OVERLAP <= overlap < CHUNK_OVERLAP + 5
    assert all(token_count(embedder.tokenizer, chunk) <= CHUNK_SIZE for chunk in chunks)
    assert re.search(r"39$", chunks[-1])


def test_real_embedding_is_repeatable_and_rejects_empty_text(embedder):
    first, second = embedder.encode(["ovo", "ovo"])
    assert len(first) == DIMENSION
    assert first == pytest.approx(second, abs=1e-6)
    assert sum(value * value for value in first) == pytest.approx(1)
    with pytest.raises(ValueError, match="Texto vazio"):
        embedder.encode(["   "])
