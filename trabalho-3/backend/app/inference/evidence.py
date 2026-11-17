"""evidence_set do turno: o que as ferramentas MCP REALMENTE retornaram nesta consulta.

Só cresce (append-only) e guarda cópias profundas dos resultados; quem lê recebe visões
somente leitura. É a única fonte de IDs, URLs, ingredientes e passos aceitos na resposta.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app.guardrails.lexicon import injection_signals
from app.integrations.mcp_client import ToolCallResult


@dataclass(frozen=True)
class SearchHit:
    recipe_id: str
    document_id: str
    title: str
    topic_key: str
    source_url: str
    source_excerpt: str
    compatibility: str
    available_ingredients: tuple[str, ...]
    missing_ingredients: tuple[str, ...]


class EvidenceSet:
    def __init__(self) -> None:
        self._results: list[ToolCallResult] = []
        self._hits: dict[str, SearchHit] = {}
        self._documents: dict[str, Mapping[str, Any]] = {}
        self._topics: list[Mapping[str, Any]] = []
        self._topics_seen = False
        self._corpus_empty = False

    # ------------------------------------------------------------ escrita (somente acréscimo)

    def add(self, result: ToolCallResult) -> None:
        data = copy.deepcopy(result.data)
        self._results.append(ToolCallResult(result.name, data, result.duration_ms, result.request_id))
        err = data.get("error") or {}
        if isinstance(err, Mapping) and err.get("code") == "CORPUS_EMPTY":
            self._corpus_empty = True
        if result.name == "search_knowledge":
            for r in data.get("results") or []:
                self._hits.setdefault(
                    r["recipe_id"],
                    SearchHit(
                        recipe_id=r["recipe_id"],
                        document_id=r["document_id"],
                        title=r["title"],
                        topic_key=r["topic_key"],
                        source_url=r["source_url"],
                        source_excerpt=r.get("source_excerpt") or "",
                        compatibility=r.get("compatibility") or "NOT_EVALUATED",
                        available_ingredients=tuple(r.get("available_ingredients") or ()),
                        missing_ingredients=tuple(r.get("missing_ingredients") or ()),
                    ),
                )
        elif result.name == "get_document" and data.get("found") and isinstance(data.get("recipe"), Mapping):
            rec = data["recipe"]
            self._documents.setdefault(rec["recipe_id"], MappingProxyType(rec))
        elif result.name == "list_topics":
            self._topics_seen = True
            if data.get("corpus_ready"):
                self._topics = [MappingProxyType(t) for t in data.get("topics") or []]

    # ------------------------------------------------------------ leitura

    @property
    def results(self) -> tuple[ToolCallResult, ...]:
        return tuple(self._results)

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(r.name for r in self._results)

    @property
    def hits(self) -> Mapping[str, SearchHit]:
        return MappingProxyType(self._hits)

    @property
    def documents(self) -> Mapping[str, Mapping[str, Any]]:
        return MappingProxyType(self._documents)

    @property
    def topics(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._topics)

    @property
    def topics_seen(self) -> bool:
        return self._topics_seen

    @property
    def corpus_empty(self) -> bool:
        return self._corpus_empty and not self._hits and not self._documents

    @property
    def recipe_ids(self) -> frozenset[str]:
        return frozenset(self._hits) | frozenset(self._documents)

    def recipe_source(self, recipe_id: str) -> Mapping[str, Any] | None:
        """Dados de identificação da receita (prefere o objeto integral de get_document)."""
        doc = self._documents.get(recipe_id)
        if doc is not None:
            return doc
        hit = self._hits.get(recipe_id)
        if hit is None:
            return None
        return {"recipe_id": hit.recipe_id, "document_id": hit.document_id, "title": hit.title,
                "topic_key": hit.topic_key, "source_url": hit.source_url}

    @property
    def allowed_urls(self) -> frozenset[str]:
        urls = {h.source_url for h in self._hits.values()}
        urls |= {d["source_url"] for d in self._documents.values() if d.get("source_url")}
        urls |= {d["revision_url"] for d in self._documents.values() if d.get("revision_url")}
        return frozenset(urls)

    @property
    def allowed_ids(self) -> frozenset[str]:
        ids = set(self.recipe_ids)
        ids |= {h.document_id for h in self._hits.values()}
        ids |= {d["document_id"] for d in self._documents.values()}
        return frozenset(ids)

    def ingredient_names(self, recipe_ids: Iterable[str] | None = None) -> frozenset[str]:
        """Nomes de ingredientes documentados (receitas indicadas, ou todas do turno)."""
        wanted = set(recipe_ids) if recipe_ids is not None else None
        names: set[str] = set()
        for rid, hit in self._hits.items():
            if wanted is None or rid in wanted:
                names |= set(hit.available_ingredients) | set(hit.missing_ingredients)
        for rid, doc in self._documents.items():
            if wanted is None or rid in wanted:
                for ing in doc.get("ingredients") or []:
                    names.add(ing.get("name_original", ""))
                    names.add(ing.get("name_normalized", ""))
                    names |= set(ing.get("alternatives_documented") or [])
        return frozenset(n for n in names if n)

    def alternatives(self) -> frozenset[str]:
        out: set[str] = set()
        for doc in self._documents.values():
            for ing in doc.get("ingredients") or []:
                out |= set(ing.get("alternatives_documented") or [])
        return frozenset(out)

    def documented_text(self) -> str:
        """Texto documental do turno (para conferir números, tempos, temperaturas e alegações)."""
        parts: list[str] = []
        for hit in self._hits.values():
            parts += [hit.title, hit.source_excerpt]
        for doc in self._documents.values():
            parts.append(doc.get("title", ""))
            parts += list(doc.get("instructions") or [])
            for ing in doc.get("ingredients") or []:
                parts += [ing.get("name_original") or "", ing.get("quantity_text") or "", ing.get("notes") or ""]
            opt = doc.get("optional_fields") or {}
            portions = opt.get("portions")
            if portions:
                # "4" -> "rende 4 porções"; "6 fatias" fica como está
                parts.append(f"rende {portions} porções" if str(portions).strip().isdigit() else str(portions))
            parts += [str(opt[k]) for k in ("preparation_time", "temperature") if opt.get(k)]
        for t in self._topics:
            parts.append(str(t.get("label", "")))
        # Trechos com instruções embutidas não são fatos: não podem "autorizar" uma alegação.
        return "\n".join(p for p in parts if p and not injection_signals(p))
