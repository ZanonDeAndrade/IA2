"""Consulta os trechos indexados e recupera a página original do PDF."""
import argparse
import json
import re
import sys
from collections import Counter
from hashlib import sha256
from math import isfinite
from pathlib import Path

from .embed import MODEL_NAME, MODEL_REVISION, Embedder
from .extract import pdf_url
from .ingredients import normalize_text
from .vector_store import DEFAULT_DATA, VectorStore, index_metadata

INVENTORY_QUERY = re.compile(
    r"^(?:o que (?:posso )?(?:fazer|preparar|cozinhar)|que (?:receitas?|pratos?)"
    r"(?: posso (?:fazer|preparar))?|(?:ideia|ideias|receita|receitas|sugestao|sugestoes)) com (.+)$"
)
QUERY_WORDS = frozenset(
    "a ao as com como da das de do dos e essa este fazer ha liste me modo mostre na nas no nos "
    "o os para posso pode podem preparo preparar qual quais que receita receitas tem um uma voce voces quero "
    "encontro encontrar gostaria diga indique sugira cozinhar ingredientes utilizar usar"
    .split()
)


class InvalidQuery(ValueError):
    pass


def search_terms(text: str) -> list[str]:
    return [word for word in normalize_text(text).split() if word not in QUERY_WORDS]


def valid_pdf_source(page: dict) -> bool:
    filename = page.get("source_filename")
    number = page.get("page")
    return (
        isinstance(filename, str) and Path(filename).name == filename and Path(filename).suffix.lower() == ".pdf"
        and type(number) is int and number > 0 and page.get("source_url") == pdf_url(filename, number)
        and bool(page.get("text"))
    )


class Retriever:
    def __init__(
        self,
        chroma_path: Path = DEFAULT_DATA / "chroma",
        recipes_path: Path = DEFAULT_DATA / "normalized" / "recipes.json",
        *,
        offline: bool = False,
    ):
        self.offline = offline
        self.embedder = None
        self.recipes = {}
        self.topics = Counter()
        self.page_text = {}
        self.page_terms = {}
        self.collection = None
        if not recipes_path.is_file() or not (chroma_path / "chroma.sqlite3").is_file():
            return
        corpus = recipes_path.read_bytes()
        recipes = json.loads(corpus)
        self.collection = VectorStore(chroma_path).open(index_metadata(corpus))
        if self.collection is None or self.collection.count() != self.collection.metadata.get("chunk_count"):
            return
        self.recipes = {page["recipe_id"]: page for page in recipes if valid_pdf_source(page)}
        self.labels = {page["topic_key"]: page["title"] for page in self.recipes.values()}
        self.page_text = {key: f" {normalize_text(page['text'])} " for key, page in self.recipes.items()}
        self.page_terms = {key: search_terms(page["text"]) for key, page in self.recipes.items()}
        self.topics = Counter(recipe["topic_key"] for recipe in self.recipes.values())

    def get_document(self, recipe_id: str) -> dict:
        page = self.recipes.get(recipe_id)
        if page is None:
            return {"found": False, "error": {"code": "DOCUMENT_NOT_FOUND", "message": "Página não encontrada."}}
        return {"found": True, "recipe": page}

    def list_topics(self, include_counts: bool = True) -> dict:
        topics = []
        for key, count in sorted(self.topics.items()):
            topic = {"topic_key": key, "label": self.labels[key]}
            if include_counts:
                topic["page_count"] = count
            topics.append(topic)
        return {"topics": topics, "total_topics": len(topics), "corpus_ready": bool(self.recipes)}

    def search(
        self,
        query: str,
        available_ingredients: list[str] | None = None,
        topic_key: str | None = None,
        top_k: int = 8,
        *,
        include_trace: bool = False,
    ) -> dict:
        if not isinstance(query, str) or not 3 <= len(query.strip()) <= 500:
            raise InvalidQuery("A pergunta deve ter entre 3 e 500 caracteres")
        if type(top_k) is not int or not 1 <= top_k <= 10:
            raise InvalidQuery("top_k deve ser inteiro de 1 a 10")
        if available_ingredients is not None and (
            not isinstance(available_ingredients, list)
            or len(available_ingredients) > 30
            or any(not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 for name in available_ingredients)
        ):
            raise InvalidQuery("Informe até 30 ingredientes com 1 a 80 caracteres cada")
        if topic_key is not None and (not isinstance(topic_key, str) or (self.topics and topic_key not in self.topics)):
            raise InvalidQuery("Tópico desconhecido")

        result = {"query": query, "evidence_status": "INSUFFICIENT", "retrieved_count": 0, "results": []}
        if include_trace:
            result["trace"] = []
        if not self.recipes:
            result["error"] = {"code": "CORPUS_EMPTY", "message": "O corpus ainda não está indexado."}
            return result

        question = normalize_text(query)
        ordered_terms = search_terms(question)
        supplied = available_ingredients
        if supplied is None and INVENTORY_QUERY.fullmatch(question):
            suffix = re.split(r"\bcom\s+", query, maxsplit=1, flags=re.IGNORECASE)[-1]
            supplied = [
                item.strip(" ?.\t")
                for item in re.split(r"[,;]|\s+e\s+", suffix)
                if item.strip(" ?.\t")
            ]
        inventory_terms = {ingredient: normalize_text(ingredient) for ingredient in (supplied or [])}
        filters = [{"topic_key": topic_key}] if topic_key else []
        if topic_key:
            topic_words = set(search_terms(self.labels[topic_key]))
            ordered_terms = [term for term in ordered_terms if term not in topic_words]
        terms = set(ordered_terms)
        if len(terms) > 1 and not inventory_terms:
            phrase = f" {' '.join(ordered_terms)} "
            exact_pages = [
                key for key, words in self.page_terms.items()
                if (not topic_key or self.recipes[key]["topic_key"] == topic_key)
                and phrase in f" {' '.join(words)} "
            ]
            if exact_pages:
                filters.append({"recipe_id": {"$in": exact_pages}})
        where = {"$and": filters} if len(filters) > 1 else next(iter(filters), None)

        if self.embedder is None:
            self.embedder = Embedder(offline=self.offline)
        embedding_query = " ".join([query, *inventory_terms])
        vector = self.embedder.encode([embedding_query], truncate=True)[0]
        found = self.collection.query(
            query_embeddings=[vector],
            n_results=min(top_k, self.collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        candidates = {}
        for chunk_id, text, metadata, distance in zip(
            found["ids"][0], found["documents"][0], found["metadatas"][0], found["distances"][0], strict=True
        ):
            if not self._valid_candidate(text, metadata, distance):
                continue
            recipe_id = metadata["recipe_id"]
            page = self.recipes[recipe_id]
            if include_trace:
                result["trace"].append({
                    "chunk_id": chunk_id, "recipe_id": recipe_id, "page": page["page"], "distance": distance,
                })
            page_text = self.page_text[recipe_id]
            mentioned_ingredients = [
                ingredient for ingredient, name in inventory_terms.items() if name and f" {name} " in page_text
            ]
            matched_terms = terms.intersection(self.page_terms[recipe_id])
            if inventory_terms:
                supported = bool(mentioned_ingredients)
            elif terms:
                supported = len(matched_terms) >= min(2, len(terms))
            else:
                supported = bool(topic_key)
            if not supported:
                continue

            rank = (
                -len(mentioned_ingredients), -len(matched_terms), -len(terms.intersection(search_terms(text))), distance,
            )
            existing = candidates.get(recipe_id)
            if existing is None or rank < existing[0]:
                candidates[recipe_id] = (rank, {
                    **{key: page[key] for key in (
                        "recipe_id", "document_id", "title", "topic_key", "source_url", "source_filename", "page",
                    )},
                    "source_excerpt": text,
                    "chunk_id": chunk_id,
                    "distance": distance,
                    "mentioned_ingredients": mentioned_ingredients,
                    "compatibility": None,
                    "available_ingredients": [],
                    "missing_ingredients": [],
                })

        result["retrieved_count"] = len(found["ids"][0])
        result["results"] = [item for _, item in sorted(candidates.values(), key=lambda pair: pair[0])[:5]]
        if candidates:
            result["evidence_status"] = "FOUND"
        return result

    def _valid_candidate(self, text, metadata, distance) -> bool:
        if not text or not metadata or not isinstance(distance, (int, float)) or not isfinite(distance):
            return False
        recipe = self.recipes.get(metadata.get("recipe_id"))
        return bool(
            recipe
            and all(metadata.get(key) == recipe[key] for key in ("document_id", "topic_key", "source_url", "source_filename", "page"))
            and metadata.get("embedding_model") == MODEL_NAME
            and metadata.get("embedding_revision") == MODEL_REVISION
            and metadata.get("content_hash") == sha256(text.encode()).hexdigest()
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?")
    parser.add_argument("--ingredient", action="append", dest="ingredients")
    parser.add_argument("--topic")
    parser.add_argument("--top-k", type=int, default=8)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--document")
    actions.add_argument("--topics", action="store_true")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--chroma-path", type=Path, default=DEFAULT_DATA / "chroma")
    parser.add_argument("--recipes", type=Path, default=DEFAULT_DATA / "normalized" / "recipes.json")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if sum(bool(action) for action in (args.query, args.document, args.topics)) != 1:
        parser.error("Informe uma pergunta, --document ou --topics")
    try:
        retriever = Retriever(args.chroma_path, args.recipes, offline=args.offline)
        if args.document:
            result = retriever.get_document(args.document)
        elif args.topics:
            result = retriever.list_topics()
        else:
            result = retriever.search(args.query, args.ingredients, args.topic, args.top_k, include_trace=args.trace)
    except Exception as exc:
        print(f"Falha na recuperação: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
