"""Seleção e ordenação programática das receitas recomendadas (o LLM não decide sozinho).

Entrada: plano da consulta, evidência MCP do turno (compatibilidade já calculada pelo servidor MCP) e os
recipe_ids que o LLM escolheu. Saída: receitas elegíveis, na ordem documentada, e a situação da resposta.

Elegibilidade (depende da intenção):
- busca por ingredientes/característica/categoria COM ingredientes: só COMPLETE ou PARTIAL (receita sem nenhum
  ingrediente em comum não é recomendação);
- busca por nome ou modo de preparo: o título precisa conter o prato pedido (palavra principal + maior número de
  palavras em comum); a compatibilidade é informada, mas não exclui;
- demais casos: qualquer receita retornada pelas ferramentas neste turno.

Ordem (lexicográfica, sem pesos arbitrários):
  1. COMPLETE antes de PARTIAL antes de NOT_EVALUATED/NO_MATCH  (o que dá para preparar agora vem primeiro)
  2. menos ingredientes faltantes                               (menos compras)
  3. mais ingredientes do usuário usados                        (aproveita o que ele tem)
  4. menor distância semântica no índice                        (mais próxima do pedido)
  5. ordem de recomendação do LLM e, por fim, a ordem do MCP
Receitas COMPLETE elegíveis sempre entram, mesmo que o LLM não as tenha citado (situação A).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from app.guardrails import lexicon
from app.inference.evidence import EvidenceSet, SearchHit
from app.inference.intent import NAME_INTENTS, QueryPlan

COMPAT_ORDER = {"COMPLETE": 0, "PARTIAL": 1, "NOT_EVALUATED": 2, "NO_MATCH": 3}
_TITLE_STOP = {"receita", "de", "da", "do", "das", "dos", "com", "e", "a", "o", "versao", "um", "uma", "para", "em"}

Situation = Literal["CAN_PREPARE", "NEEDS_INGREDIENTS", "NOT_EVALUATED", "NONE"]


@dataclass(frozen=True)
class Selection:
    recipe_ids: tuple[str, ...]
    situation: Situation
    changed: bool  # a seleção final difere (além da ordem) do que o LLM escolheu
    candidates: int


def _dish_terms(dish: str) -> list[str]:
    return [w for w in lexicon.words(dish) if w not in _TITLE_STOP]


def name_score(dish: str | None, title: str) -> int:
    """Palavras do prato presentes no título; 0 se a palavra principal (a primeira) não estiver."""
    terms = _dish_terms(dish or "")
    if not terms:
        return 0
    title_words = set(lexicon.words(title))
    if terms[0] not in title_words:
        return 0
    return sum(1 for t in terms if t in title_words)


def rank_key(hit: SearchHit, llm_rank: dict[str, int], mcp_rank: dict[str, int]) -> tuple:
    return (
        COMPAT_ORDER.get(hit.compatibility, 3),
        len(hit.missing_ingredients),
        -len(hit.available_ingredients),
        hit.distance if hit.distance is not None else math.inf,
        llm_rank.get(hit.recipe_id, len(llm_rank)),
        mcp_rank.get(hit.recipe_id, len(mcp_rank)),
    )


def eligible_hits(plan: QueryPlan, evidence: EvidenceSet) -> list[SearchHit]:
    hits = list(evidence.hits.values())
    if plan.intent in NAME_INTENTS:
        scored = [(name_score(plan.dish, h.title), h) for h in hits]
        best = max((s for s, _ in scored), default=0)
        return [h for s, h in scored if s and s == best]
    if plan.ingredients:
        return [h for h in hits if h.compatibility in ("COMPLETE", "PARTIAL")]
    return hits


def select(plan: QueryPlan, evidence: EvidenceSet, llm_ids: tuple[str, ...], max_recipes: int) -> Selection:
    if plan.intent == "list_categories":
        return Selection((), "NONE", False, 0)
    cands = eligible_hits(plan, evidence)
    by_id = {h.recipe_id: h for h in cands}
    llm_rank = {rid: i for i, rid in enumerate(llm_ids)}
    mcp_rank = {rid: i for i, rid in enumerate(evidence.hits)}
    llm_valid = [rid for rid in llm_ids if rid in by_id]

    chosen: set[str] = set(llm_valid)
    if not llm_valid and (plan.ingredients or plan.intent in NAME_INTENTS):
        # Critério estruturado disponível (ingredientes em comum ou título): não depende do LLM.
        chosen = set(by_id)
    elif plan.ingredients:
        chosen |= {h.recipe_id for h in cands if h.compatibility == "COMPLETE"}  # situação A sempre aparece
    ordered = sorted((by_id[r] for r in chosen), key=lambda h: rank_key(h, llm_rank, mcp_rank))[:max_recipes]
    ids = tuple(h.recipe_id for h in ordered)

    if not ids:
        situation: Situation = "NONE"
    elif not plan.ingredients or plan.intent in NAME_INTENTS and all(
            h.compatibility == "NOT_EVALUATED" for h in ordered):
        situation = "NOT_EVALUATED"
    elif any(h.compatibility == "COMPLETE" for h in ordered):
        situation = "CAN_PREPARE"
    else:
        situation = "NEEDS_INGREDIENTS"
    return Selection(ids, situation, set(ids) != set(llm_valid), len(cands))


# ---------------------------------------------------------------- texto determinístico (fallback)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " e " + items[-1]


def template_answer(plan: QueryPlan, evidence: EvidenceSet, selection: Selection) -> str:
    """Resposta montada só com a evidência e a compatibilidade calculada (nenhum texto livre do LLM)."""
    hits = [evidence.hits[r] for r in selection.recipe_ids if r in evidence.hits]
    titles = {r: (evidence.recipe_source(r) or {}).get("title", r) for r in selection.recipe_ids}
    lines: list[str] = []
    if plan.ingredients and plan.intent not in NAME_INTENTS:
        complete = [h for h in hits if h.compatibility == "COMPLETE"]
        partial = [h for h in hits if h.compatibility == "PARTIAL"]
        if complete:
            lines.append("Com os ingredientes que você informou, dá para preparar: "
                         + _join([titles[h.recipe_id] for h in complete])
                         + ". Você tem todos os ingredientes obrigatórios; confira as quantidades.")
        else:
            lines.append("Não encontrei na base receitas que usem apenas os ingredientes informados.")
        if partial:
            lines.append(("Com ingredientes adicionais" if complete else "Estas exigem ingredientes adicionais") + ":")
            for h in partial:
                lines.append(f"- {titles[h.recipe_id]}: falta(m) {_join(list(h.missing_ingredients))}.")
    else:
        lines.append("Encontrei na base documental: " + _join([titles[r] for r in selection.recipe_ids]) + ".")
        for h in hits:
            if h.compatibility == "PARTIAL":
                lines.append(f"- {titles[h.recipe_id]}: falta(m) {_join(list(h.missing_ingredients))}.")
            elif h.compatibility == "NO_MATCH" and plan.ingredients:
                lines.append(f"- {titles[h.recipe_id]}: não usa nenhum dos ingredientes informados.")
    lines.append("Ingredientes e modo de preparo estão nos cards, reproduzidos da fonte indicada.")
    return "\n".join(lines)


def insufficient_answer(plan: QueryPlan) -> str:
    if plan.intent in NAME_INTENTS and plan.dish:
        return (f"Não encontrei \"{plan.dish}\" na base documental de receitas. "
                "Tente outro prato ou informe os ingredientes que você tem.")
    if plan.ingredients:
        return ("Não encontrei na base receitas que usem os ingredientes informados "
                f"({_join(list(plan.ingredients))}). Tente acrescentar outros ingredientes.")
    return ("Não encontrei na base documental receitas que atendam a esse pedido. "
            "Tente informar ingredientes ou o nome de um prato.")
