import json
from hashlib import sha256
from pathlib import Path

from .chunk import CHUNK_FORMAT, CHUNK_OVERLAP, CHUNK_SIZE, Chunk
from .embed import DIMENSION, MODEL_NAME, MODEL_REVISION, validate_vector

COLLECTION_PREFIX = "recipes_v1_multilingual_minilm"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data"
INDEX_FORMAT = {
    "chunk_format": CHUNK_FORMAT,
    "chunk_size": CHUNK_SIZE,
    "chunk_overlap": CHUNK_OVERLAP,
    "embedding_dimensions": DIMENSION,
    "embedding_model": MODEL_NAME,
    "embedding_revision": MODEL_REVISION,
    "distance_metric": "cosine",
}


def index_metadata(corpus: bytes) -> dict:
    return {**INDEX_FORMAT, "corpus_sha256": sha256(corpus).hexdigest()}


def collection_name(metadata: dict) -> str:
    digest = sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    return f"{COLLECTION_PREFIX}_{digest[:24]}"


class VectorStore:
    def __init__(self, path: Path):
        from chromadb import PersistentClient
        from chromadb.config import Settings

        self.client = PersistentClient(path=str(path.resolve()), settings=Settings(anonymized_telemetry=False))

    def open(self, metadata: dict):
        from chromadb.errors import NotFoundError

        try:
            collection = self.client.get_collection(collection_name(metadata), embedding_function=None)
        except NotFoundError:
            return None
        if any(collection.metadata.get(key) != value for key, value in metadata.items()):
            raise ValueError("Coleção incompatível com o corpus ou o modelo")
        return collection

    def publish(self, metadata: dict, chunks: list[Chunk], embeddings: list[list[float]]):
        if not chunks or len(chunks) != len(embeddings):
            raise ValueError("Cada chunk precisa de um embedding")
        for vector in embeddings:
            validate_vector(vector)
        name = collection_name(metadata)
        existing = self.open(metadata)
        if existing is not None:
            self.client.delete_collection(name)
        collection = self.client.create_collection(
            name,
            metadata=metadata,
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
        )
        try:
            collection.upsert(
                ids=[chunk.chunk_id for chunk in chunks],
                embeddings=embeddings,
                documents=[chunk.text for chunk in chunks],
                metadatas=[chunk.metadata for chunk in chunks],
            )
            if collection.count() != len(chunks):
                raise ValueError("A contagem do índice não corresponde aos chunks")
            collection.modify(metadata={**metadata, "chunk_count": len(chunks)})
        except Exception:
            self.client.delete_collection(name)
            raise
        return collection
