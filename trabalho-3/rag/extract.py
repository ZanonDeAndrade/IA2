"""Extração local de texto de PDFs, preservando a numeração física das páginas."""
from hashlib import sha256
from pathlib import Path
from subprocess import run
from unicodedata import normalize
from urllib.parse import quote

from .ingredients import normalize_text


def pdf_url(filename: str, page: int) -> str:
    return f"data/raw/{quote(filename, safe='')}#page={page}"


def read_pdf(path: Path) -> tuple[dict, list[dict]]:
    raw = path.read_bytes()
    digest = sha256(raw).hexdigest()
    # Git e o sistema de arquivos podem representar o mesmo nome com acentos diferentes.
    identity = sha256(normalize("NFD", path.name).encode())
    identity.update(raw)
    document_id = f"pdf-{identity.hexdigest()[:16]}"
    title = " ".join(path.stem.replace("_", " ").split())
    topic_key = normalize_text(title).replace(" ", "-") or document_id

    try:
        result = run(["pdftotext", "-enc", "UTF-8", "-", "-"], input=raw, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise ValueError("pdftotext ausente. Instale o Poppler (brew install poppler ou sudo apt install poppler-utils).") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(detail or "o Poppler não conseguiu abrir o PDF")

    pages = result.stdout.decode("utf-8").removesuffix("\f").split("\f")
    indexed, empty = [], []
    for number, page_text in enumerate(pages, 1):
        text = page_text.strip()
        if not any(char.isalnum() for char in text):
            empty.append(number)
            continue
        indexed.append({
            "recipe_id": f"{document_id}-p{number}",
            "document_id": document_id,
            "title": title,
            "topic_key": topic_key,
            "source_filename": path.name,
            "source_url": pdf_url(path.name, number),
            "page": number,
            "text": text,
        })
    if not indexed:
        raise ValueError("nenhuma página com texto extraível. Gere uma camada de texto com OCR e tente novamente.")

    source = {
        "document_id": document_id,
        "title": title,
        "topic_key": topic_key,
        "snapshot": path.name,
        "sha256": digest,
        "pages": len(pages),
        "pages_indexed": len(indexed),
        "pages_without_text": empty,
    }
    return source, indexed
