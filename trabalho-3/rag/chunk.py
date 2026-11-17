from dataclasses import dataclass
from hashlib import sha256

from .embed import MODEL_NAME, MODEL_REVISION

CHUNK_SIZE = 100
CHUNK_OVERLAP = 20
CHUNK_FORMAT = 3


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str
    metadata: dict[str, str | int]


def token_count(tokenizer, text: str) -> int:
    return len(tokenizer(text, add_special_tokens=True, verbose=False)["input_ids"])


def build_chunks(page: dict, tokenizer) -> list[Chunk]:
    text = " ".join(page["text"].split())
    chunks = []
    for index, excerpt in enumerate(split_text(text, tokenizer)):
        digest = sha256(excerpt.encode()).hexdigest()
        chunks.append(Chunk(
            chunk_id=f"{page['recipe_id']}-{index}-{digest[:12]}",
            text=excerpt,
            metadata={
                "recipe_id": page["recipe_id"],
                "document_id": page["document_id"],
                "topic_key": page["topic_key"],
                "source_url": page["source_url"],
                "source_filename": page["source_filename"],
                "page": page["page"],
                "content_hash": digest,
                "embedding_model": MODEL_NAME,
                "embedding_revision": MODEL_REVISION,
                "tokenizer_tokens": token_count(tokenizer, excerpt),
            },
        ))
    return chunks


def split_text(text: str, tokenizer):
    offsets = tokenizer(
        text, add_special_tokens=False, return_offsets_mapping=True, verbose=False
    )["offset_mapping"]
    budget = CHUNK_SIZE - tokenizer.num_special_tokens_to_add(pair=False)
    word_starts = {0, len(offsets)}
    word_starts.update(
        index for index, (offset, _) in enumerate(offsets)
        if offset and (text[offset - 1].isspace() or text[offset].isspace())
    )
    start = 0
    while start < len(offsets):
        limit = min(start + budget, len(offsets))
        end = max((index for index in word_starts if start + CHUNK_OVERLAP < index <= limit), default=limit)
        chunk = ""
        while end > start:
            chunk = text[offsets[start][0]:offsets[end - 1][1]].strip()
            if token_count(tokenizer, chunk) <= CHUNK_SIZE:
                break
            end -= 1
        if end == len(offsets):
            yield chunk
            return
        if end - start <= CHUNK_OVERLAP:
            raise ValueError("Página sem espaço suficiente para segmentação")
        yield chunk
        target = end - CHUNK_OVERLAP
        start = max((index for index in word_starts if start < index <= target), default=target)
