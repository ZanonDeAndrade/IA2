from math import isfinite

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
DIMENSION = 384


def validate_vector(vector: list[float]) -> None:
    if len(vector) != DIMENSION or not all(isfinite(value) for value in vector) or not any(vector):
        raise ValueError(f"Embedding inválido: são esperados {DIMENSION} valores finitos e norma positiva")


class Embedder:
    def __init__(self, *, offline: bool = False):
        from huggingface_hub import snapshot_download
        from sentence_transformers import SentenceTransformer

        model_path = snapshot_download(
            MODEL_NAME,
            revision=MODEL_REVISION,
            local_files_only=offline,
            allow_patterns=[
                "*.json", "1_Pooling/config.json", "model.safetensors", "sentencepiece.bpe.model",
            ],
        )
        self.model = SentenceTransformer(
            model_path,
            device="cpu",
            local_files_only=True,
            model_kwargs={"use_safetensors": True},
        )
        if self.model.get_sentence_embedding_dimension() != DIMENSION:
            raise ValueError("O modelo carregado tem dimensão incompatível")
        self.tokenizer = self.model.tokenizer

    def encode(self, texts: list[str], *, truncate: bool = False) -> list[list[float]]:
        if not texts:
            return []
        texts = [" ".join(text.split()) for text in texts]
        if any(not text for text in texts):
            raise ValueError("Texto vazio para embedding")
        if not truncate:
            tokens = self.tokenizer(texts, verbose=False)["input_ids"]
            if any(len(row) > self.model.max_seq_length for row in tokens):
                raise ValueError("O texto ultrapassa o limite de tokens do modelo")
        vectors = self.model.encode(texts, batch_size=32, normalize_embeddings=True).tolist()
        for vector in vectors:
            validate_vector(vector)
        return vectors
