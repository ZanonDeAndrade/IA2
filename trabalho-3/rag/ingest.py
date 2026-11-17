"""Indexa os PDFs de data/raw e publica a geração correspondente no Chroma."""
import argparse
import json
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from fcntl import LOCK_EX, flock
from pathlib import Path

from .chunk import build_chunks
from .embed import Embedder
from .extract import read_pdf
from .vector_store import DEFAULT_DATA, VectorStore, collection_name, index_metadata


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def replace_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        temp_path = Path(temp.name)
        try:
            temp.write(content)
            temp.close()
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)


def load_pages(data_dir: Path) -> tuple[list[dict], list[dict]]:
    raw_dir = data_dir / "raw"
    files = sorted(
        (path for path in raw_dir.glob("*") if path.is_file() and path.suffix.lower() == ".pdf"),
        key=lambda path: (path.name.casefold(), path.name),
    )
    if not files:
        raise ValueError(f"Nenhum PDF encontrado em {raw_dir}")

    sources, pages = [], []
    for path in files:
        try:
            source, indexed = read_pdf(path)
        except (OSError, ValueError) as exc:
            raise ValueError(f"{path.name}: {exc}") from exc
        if any(previous["topic_key"] == source["topic_key"] for previous in sources):
            source["topic_key"] = source["document_id"]
            for page in indexed:
                page["topic_key"] = source["topic_key"]
        sources.append(source)
        pages.extend(indexed)
    return sources, pages


def ingest(data_dir: Path, chroma_path: Path, recipes_path: Path, *, offline: bool = False) -> dict:
    sources, pages = load_pages(data_dir)
    corpus = json_bytes(pages)
    metadata = index_metadata(corpus)
    chroma_path.mkdir(parents=True, exist_ok=True)
    with (chroma_path / ".ingest.lock").open("a") as lock:
        flock(lock, LOCK_EX)
        store = VectorStore(chroma_path)
        collection = store.open(metadata)
        reused = bool(collection is not None and collection.count()
                      and collection.count() == collection.metadata.get("chunk_count"))
        if not reused:
            embedder = Embedder(offline=offline)
            chunks = [chunk for page in pages for chunk in build_chunks(page, embedder.tokenizer)]
            embeddings = embedder.encode([chunk.text for chunk in chunks])
            collection = store.publish(metadata, chunks, embeddings)
        records = collection.get(include=["metadatas"])
        report = {
            **metadata,
            "collection": collection_name(metadata),
            "documents": len(sources),
            "pages": sum(source["pages"] for source in sources),
            "pages_indexed": len(pages),
            "pages_without_text": {
                source["snapshot"]: source["pages_without_text"]
                for source in sources if source["pages_without_text"]
            },
            "chunks": len(records["ids"]),
            "vectors": len(records["ids"]),
            "chunks_by_topic": dict(Counter(item["topic_key"] for item in records["metadatas"])),
            "pages_by_topic": dict(Counter(page["topic_key"] for page in pages)),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reused": reused,
            "errors": [],
        }
        replace_file(data_dir / "sources" / "manifest.json", json_bytes(sources))
        replace_file(recipes_path, corpus)
        replace_file(chroma_path / "report.json", json_bytes(report))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--chroma-path", type=Path)
    parser.add_argument("--recipes", type=Path)
    parser.add_argument("--offline", action="store_true", help="Usar somente o modelo em cache")
    args = parser.parse_args()
    try:
        report = ingest(
            args.data_dir,
            args.chroma_path or args.data_dir / "chroma",
            args.recipes or args.data_dir / "normalized" / "recipes.json",
            offline=args.offline,
        )
    except Exception as exc:
        print(f"Falha na ingestão: {exc}", file=sys.stderr)
        return 1
    print(json_bytes(report).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
