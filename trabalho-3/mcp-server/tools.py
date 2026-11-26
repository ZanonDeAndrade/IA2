"""Implementação das três tools MCP: search_knowledge, get_document e list_topics.

As funções aqui não conhecem o transporte; `server.py` as registra no MCPServer.
Erros de entrada/execução são sinalizados com `ToolFailure(code, message)`; resultados de
negócio (base vazia, documento inexistente) voltam como saída estruturada.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from models import (
    Compatibility,
    Ranking,
    GetDocumentOutput,
    IngredientOut,
    ListTopicsOutput,
    MatchedChunk,
    OptionalFields,
    RecipeOut,
    SearchKnowledgeOutput,
    SearchResult,
    ToolErrorInfo,
    TopicOut,
)
from store import Hit, RecipeRecord, RecipeStore, RetrieverAdapter, RetrieverUnavailable, basic_normalize

logger = logging.getLogger("mcp_server.tools")

MAX_RESULTS = 5
# No modo compatibilidade o LLM recebe mais candidatos para julgar a adequação ao pedido (ocasião, tipo de prato),
# que não está nos metadados; quem garante a compatibilidade e a ordem final continua sendo o sistema.
MAX_RESULTS_COMPATIBILITY = 8
EXCERPT_CHARS = 500
# Quantos chunks pedir ao índice antes de agrupar por receita e ordenar. O top_k do LLM (1..10) limitaria o
# ranking a ~5 receitas; o conjunto maior permite que a compatibilidade escolha entre candidatos suficientes.
CANDIDATE_CHUNKS = 60
RELEVANCE_CHUNKS = 20
COMPAT_ORDER = {"COMPLETE": 0, "PARTIAL": 1, "NOT_EVALUATED": 2, "NO_MATCH": 3}
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ToolFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class ToolContext:
    store: RecipeStore
    retriever: RetrieverAdapter
    normalize: Callable[[str], str]
    # chaves de receita satisfeitas por um ingrediente do usuário (partes e genéricos); None = igualdade
    user_keys: Callable[[str], Iterable[str]] | None = None


# ---------------------------------------------------------------- utilitários


def _clean_text(value: str, field: str) -> str:
    if _CONTROL_RE.search(value):
        raise ToolFailure("INVALID_TOOL_ARGUMENTS", f"{field} contém caracteres de controle")
    return " ".join(value.split())


def _clean_ingredients(items: Iterable[str] | None) -> list[str] | None:
    if items is None:
        return None
    seen: dict[str, None] = {}
    for item in items:
        cleaned = _clean_text(item, "available_ingredients")
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


def _excerpt(text: str) -> str:
    text = _CONTROL_RE.sub(" ", text).strip()
    return text if len(text) <= EXCERPT_CHARS else text[: EXCERPT_CHARS - 1].rstrip() + "…"


def topic_label(topic_key: str, recipes: Iterable[RecipeRecord]) -> str:
    for r in recipes:
        if r.topic_key == topic_key and r.topic_label:
            return r.topic_label
    return topic_key.replace("_", " ").replace("-", " ").capitalize()


# ---------------------------------------------------------------- compatibilidade (função pura)


@dataclass(frozen=True)
class CompatibilityResult:
    available: list[str]
    missing: list[str]
    matched_required: int
    total_required: int
    status: Compatibility

    @property
    def ratio(self) -> float:
        return self.matched_required / self.total_required if self.total_required else 0.0


def user_key_set(user_ingredients: Iterable[str], normalize: Callable[[str], str],
                 user_keys: Callable[[str], Iterable[str]] | None = None) -> frozenset[str]:
    keys: set[str] = set()
    for u in user_ingredients:
        keys |= {normalize(u), basic_normalize(u)}
        if user_keys is not None:
            keys |= set(user_keys(u))
    return frozenset(k for k in keys if k)


def compute_compatibility(
    recipe: RecipeRecord,
    user_ingredients: list[str] | None,
    normalize: Callable[[str], str],
    user_keys: Callable[[str], Iterable[str]] | None = None,
) -> CompatibilityResult:
    """Presença (não quantidade) dos ingredientes obrigatórios. Opcionais não entram no denominador (RN07).

    Um ingrediente da receita coincide quando sua chave culinária normalizada está entre as chaves satisfeitas
    pelos ingredientes do usuário (mesma chave, parte do mesmo alimento ou genérico de uma variedade informada).
    Alternativas e substitutos NÃO contam como equivalentes (RN03).
    """
    required = [ing for ing in recipe.ingredients if ing.required]
    total = len(required)
    if not user_ingredients or total == 0:
        return CompatibilityResult([], [], 0, total, "NOT_EVALUATED")

    supplied = user_key_set(user_ingredients, normalize, user_keys)
    available: list[str] = []
    missing: list[str] = []
    for ing in required:
        keys = {normalize(ing.name_original), basic_normalize(ing.name_original)}
        if ing.name_normalized:
            keys.add(ing.name_normalized)
        (available if keys & supplied else missing).append(ing.name_original)

    matched = len(available)
    if matched == total:
        status: Compatibility = "COMPLETE"
    elif matched > 0:
        status = "PARTIAL"
    else:
        status = "NO_MATCH"
    return CompatibilityResult(available, missing, matched, total, status)


# ---------------------------------------------------------------- tools


def search_knowledge(
    ctx: ToolContext,
    query: str,
    available_ingredients: list[str] | None,
    topic_key: str | None,
    top_k: int,
    ranking: Ranking | None = None,
) -> SearchKnowledgeOutput:
    """Recuperação híbrida + ranking.

    - relevance: ordena pela distância semântica (melhor chunk da receita).
    - compatibility (padrão quando há ingredientes): candidatos = receitas do conjunto semântico ampliado
      + receitas do corpus que usam ao menos um ingrediente informado (critério estruturado). Só ficam
      COMPLETE e PARTIAL, ordenadas por: COMPLETE antes de PARTIAL; menos faltantes; mais ingredientes do
      usuário usados; menor distância semântica. Ordem lexicográfica, sem pesos arbitrários.
    """
    query = _clean_text(query, "query")
    if len(query) < 3:
        raise ToolFailure("INVALID_TOOL_ARGUMENTS", "query deve ter ao menos 3 caracteres úteis")
    ingredients = _clean_ingredients(available_ingredients)
    mode: Ranking = ranking or ("compatibility" if ingredients else "relevance")
    if not ingredients:
        mode = "relevance"  # sem ingredientes não há compatibilidade para ordenar

    snap = ctx.store.snapshot()

    def empty(error: ToolErrorInfo | None = None, chunks: int = 0, discarded: int = 0) -> SearchKnowledgeOutput:
        return SearchKnowledgeOutput(
            query=query,
            evidence_status="INSUFFICIENT",
            ranking=mode,
            retrieved_count=0,
            chunks_retrieved=chunks,
            discarded_hits=discarded,
            results=[],
            error=error,
        )

    if not snap.ready:
        return empty(ToolErrorInfo(code="CORPUS_EMPTY", message="A base de receitas ainda não foi preparada."))

    if topic_key is not None:
        topics = sorted({r.topic_key for r in snap.recipes.values()})
        if topic_key not in topics:
            raise ToolFailure(
                "INVALID_TOOL_ARGUMENTS", f"topic_key desconhecido. Valores válidos: {', '.join(topics)}"
            )

    try:
        pool = max(top_k, CANDIDATE_CHUNKS if mode == "compatibility" else RELEVANCE_CHUNKS)
        hits, malformed = ctx.retriever.search(query, top_k=pool, topic_key=topic_key)
    except RetrieverUnavailable as exc:
        raise ToolFailure("RAG_UNAVAILABLE", "O índice de busca não está disponível.") from exc
    except Exception as exc:
        logger.exception("retriever falhou")
        raise ToolFailure("RAG_ERROR", "Falha ao consultar o índice de busca.") from exc

    # Agrupa por recipe_id preservando a ordem do índice; descarta hits sem lastro no corpus.
    grouped: dict[str, list[Hit]] = {}
    discarded = malformed
    for hit in hits:
        recipe = snap.recipes.get(hit.recipe_id)
        if recipe is None or recipe.document_id != hit.document_id:
            discarded += 1
            continue
        if topic_key is not None and recipe.topic_key != topic_key:
            discarded += 1
            continue
        grouped.setdefault(hit.recipe_id, []).append(hit)
    if discarded:
        logger.warning("search_knowledge: %d hits descartados por inconsistência com o corpus", discarded)

    # Critério estruturado: receitas que usam algum ingrediente informado, mesmo fora do conjunto semântico.
    if mode == "compatibility":
        for recipe in snap.recipes.values():
            if recipe.recipe_id in grouped or (topic_key is not None and recipe.topic_key != topic_key):
                continue
            if compute_compatibility(recipe, ingredients, ctx.normalize, ctx.user_keys).matched_required:
                grouped[recipe.recipe_id] = []

    scored: list[tuple[tuple, SearchResult]] = []
    for order, (recipe_id, rhits) in enumerate(grouped.items()):
        recipe = snap.recipes[recipe_id]
        compat = compute_compatibility(recipe, ingredients, ctx.normalize, ctx.user_keys)
        if mode == "compatibility" and compat.status not in ("COMPLETE", "PARTIAL"):
            continue  # sem nenhum ingrediente em comum não é recomendação por ingredientes
        distances = [h.distance for h in rhits if h.distance is not None]
        best = min(distances) if distances else None
        if rhits:
            best_hit = min(rhits, key=lambda h: h.distance if h.distance is not None else math.inf)
            excerpt = best_hit.text
        else:  # candidato estruturado: o trecho é o próprio registro do corpus
            excerpt = f"{recipe.title}. Ingredientes: " + ", ".join(i.name_original for i in recipe.ingredients)
        result = SearchResult(
            recipe_id=recipe.recipe_id,
            document_id=recipe.document_id,
            title=recipe.title,
            topic_key=recipe.topic_key,
            topic_label=recipe.topic_label,
            subcategory=recipe.subcategory,
            source_url=recipe.source_url,
            source_excerpt=_excerpt(excerpt),
            available_ingredients=compat.available,
            missing_ingredients=compat.missing,
            matched_required=compat.matched_required,
            total_required=compat.total_required,
            compatibility=compat.status,
            distance=best,
            matched_chunks=[MatchedChunk(chunk_id=h.chunk_id, section=h.section, distance=h.distance) for h in rhits],
        )
        dist = best if best is not None else math.inf
        if mode == "compatibility":
            key = (COMPAT_ORDER[compat.status], len(compat.missing), -compat.matched_required, dist, order)
        else:
            key = (dist, order)
        scored.append((key, result))

    limit = MAX_RESULTS_COMPATIBILITY if mode == "compatibility" else MAX_RESULTS
    results = [r for _, r in sorted(scored, key=lambda x: x[0])][:limit]
    if not results:
        return empty(chunks=len(hits) + malformed, discarded=discarded)
    return SearchKnowledgeOutput(
        query=query,
        evidence_status="FOUND",
        ranking=mode,
        retrieved_count=len(results),
        chunks_retrieved=len(hits) + malformed,
        discarded_hits=discarded,
        results=results,
    )


def get_document(ctx: ToolContext, recipe_id: str) -> GetDocumentOutput:
    snap = ctx.store.snapshot()
    if not snap.ready:
        return GetDocumentOutput(
            found=False, error=ToolErrorInfo(code="CORPUS_EMPTY", message="A base de receitas ainda não foi preparada.")
        )
    recipe = snap.recipes.get(recipe_id)
    if recipe is None:
        return GetDocumentOutput(
            found=False,
            error=ToolErrorInfo(code="DOCUMENT_NOT_FOUND", message="Nenhuma receita com este recipe_id."),
        )
    return GetDocumentOutput(
        found=True,
        recipe=RecipeOut(
            recipe_id=recipe.recipe_id,
            document_id=recipe.document_id,
            variant_index=recipe.variant_index,
            title=recipe.title,
            topic_key=recipe.topic_key,
            topic_label=recipe.topic_label,
            subcategory=recipe.subcategory,
            ingredients=[
                IngredientOut(
                    name_original=i.name_original,
                    name_normalized=i.name_normalized or ctx.normalize(i.name_original),
                    quantity_text=i.quantity_text,
                    required=i.required,
                    notes=i.notes,
                    alternatives_documented=i.alternatives_documented,
                )
                for i in recipe.ingredients
            ],
            instructions=recipe.instructions,
            source_url=recipe.source_url,
            license=recipe.license,
            revision_url=recipe.revision_url,
            retrieved_at=recipe.retrieved_at,
            optional_fields=OptionalFields(
                portions=recipe.portions,
                preparation_time=recipe.preparation_time,
                temperature=recipe.temperature,
            ),
        ),
    )


def list_topics(ctx: ToolContext, include_counts: bool) -> ListTopicsOutput:
    snap = ctx.store.snapshot()
    if not snap.ready:
        return ListTopicsOutput(
            topics=[],
            total_topics=0,
            total_recipes=0,
            corpus_ready=False,
            data_version=snap.data_version,
            error=ToolErrorInfo(code="CORPUS_EMPTY", message="A base de receitas ainda não foi preparada."),
        )
    counts: dict[str, int] = {}
    for r in snap.recipes.values():
        counts[r.topic_key] = counts.get(r.topic_key, 0) + 1
    recipes = list(snap.recipes.values())
    topics = [
        TopicOut(topic_key=key, label=topic_label(key, recipes), recipe_count=counts[key] if include_counts else None)
        for key in sorted(counts)
    ]
    return ListTopicsOutput(
        topics=topics,
        total_topics=len(topics),
        total_recipes=len(recipes),
        corpus_ready=True,
        data_version=snap.data_version,
    )
