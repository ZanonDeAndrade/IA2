"""Interpretação da consulta antes do uso das ferramentas.

1. O LLM classifica a intenção com saída estruturada (`format` = JSON Schema), sem ferramentas.
2. O backend VALIDA a classificação contra a própria consulta (nada de palavras-chave fixas):
   - pratos e ingredientes extraídos precisam aparecer no texto do usuário (evita alucinação);
   - quem informa ingredientes está pedindo receitas, não a lista de categorias;
   - busca por nome/modo de preparo sem prato identificável vira busca por ingredientes ou característica.
3. O plano resultante define quais ferramentas MCP o LLM pode usar e como a busca é ordenada.

Se a classificação falhar (JSON inválido), o plano padrão é buscar receitas (nunca listar categorias).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from app.guardrails import lexicon
from app.integrations.ollama_client import OllamaClient
from app.schemas.query import ConsultationInput

logger = logging.getLogger("app.intent")

Intent = Literal[
    "recipes_by_ingredients",  # o que fazer com o que tenho
    "recipe_by_name",  # receita de um prato específico
    "recipes_by_category",  # receitas de uma categoria (doces, massas...)
    "recipes_by_characteristics",  # algo rápido, para o café da manhã, doce...
    "preparation",  # como preparar um prato
    "list_categories",  # quais categorias existem
]

# Rótulos em português para o modelo (mais estáveis em modelos pequenos) -> nomes internos.
LABELS: dict[str, Intent] = {
    "receitas_por_ingredientes": "recipes_by_ingredients",
    "receita_por_nome": "recipe_by_name",
    "receitas_por_categoria": "recipes_by_category",
    "receitas_por_caracteristica": "recipes_by_characteristics",
    "modo_de_preparo": "preparation",
    "listar_categorias": "list_categories",
}
NAME_INTENTS = frozenset({"recipe_by_name", "preparation"})

INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intencao": {"type": "string", "enum": list(LABELS)},
        "prato": {"type": "string"},
        "ingredientes": {"type": "array", "items": {"type": "string"}, "maxItems": 30},
        "consulta": {"type": "string"},
    },
    "required": ["intencao", "prato", "ingredientes", "consulta"],
}

INTENT_PROMPT = """Classifique o pedido culinário do usuário. Responda só com JSON.

intencao:
- receitas_por_ingredientes: quer saber o que preparar com ingredientes que tem.
- receita_por_nome: pede a receita de um prato específico.
- receitas_por_categoria: quer receitas de um tipo (doces, massas, bolos, salgados...).
- receitas_por_caracteristica: descreve o que quer sem prato nem ingredientes (rápido, café da manhã, almoço, leve...).
- modo_de_preparo: pergunta como preparar/fazer um prato.
- listar_categorias: pergunta quais categorias ou tipos de receita existem (não pede receitas).

prato: nome do prato citado pelo usuário, ou "".
ingredientes: ingredientes que o usuário diz ter ou quer usar, escritos como na pergunta; [] se nenhum.
consulta: frase curta para buscar receitas (prato, ingredientes e características).

Exemplos:
"Tenho batata e cebola, o que dá pra fazer?" -> {"intencao":"receitas_por_ingredientes","prato":"","ingredientes":["batata","cebola"],"consulta":"receitas com batata e cebola"}
"Me ensina a fazer pudim" -> {"intencao":"modo_de_preparo","prato":"pudim","ingredientes":[],"consulta":"pudim"}
"Que tipos de receita existem aqui?" -> {"intencao":"listar_categorias","prato":"","ingredientes":[],"consulta":"categorias"}
"Quero um lanche leve para a tarde" -> {"intencao":"receitas_por_caracteristica","prato":"","ingredientes":[],"consulta":"lanche leve da tarde"}
"Tem receita de bolo de fubá?" -> {"intencao":"receita_por_nome","prato":"bolo de fubá","ingredientes":[],"consulta":"bolo de fubá"}"""


@dataclass(frozen=True)
class QueryPlan:
    intent: Intent
    search_query: str
    ingredients: tuple[str, ...]  # informados no campo + citados na pergunta (validados)
    dish: str | None = None
    source: Literal["llm", "fallback"] = "llm"
    corrections: tuple[str, ...] = field(default_factory=tuple)

    @property
    def tools(self) -> frozenset[str]:
        """Ferramentas MCP oferecidas ao LLM nesta consulta."""
        if self.intent == "list_categories":
            return frozenset({"list_topics"})
        return frozenset({"search_knowledge", "get_document"})

    @property
    def required_tool(self) -> str:
        return "list_topics" if self.intent == "list_categories" else "search_knowledge"

    @property
    def ranking(self) -> Literal["compatibility", "relevance"]:
        if self.ingredients and self.intent not in NAME_INTENTS:
            return "compatibility"
        return "relevance"

    def search_arguments(self) -> dict[str, Any]:
        args: dict[str, Any] = {"query": self.search_query, "ranking": self.ranking}
        if self.ingredients:
            args["available_ingredients"] = list(self.ingredients)
        return args

    def describe(self) -> str:
        """Mensagem de sistema com o plano (o LLM continua escolhendo e chamando as ferramentas)."""
        names = {
            "recipes_by_ingredients": "recomendar receitas com os ingredientes do usuário",
            "recipe_by_name": f"encontrar a receita de \"{self.dish}\"",
            "recipes_by_category": "recomendar receitas de uma categoria",
            "recipes_by_characteristics": "recomendar receitas com as características pedidas",
            "preparation": f"mostrar como preparar \"{self.dish}\"",
            "list_categories": "listar as categorias de receitas da base",
        }
        lines = [f"Análise da consulta feita pelo sistema: o usuário quer {names[self.intent]}."]
        if self.intent == "list_categories":
            lines.append("Chame list_topics e responda listando as categorias retornadas.")
        else:
            lines.append(f"Chame search_knowledge com query=\"{self.search_query}\". Não liste categorias.")
            if self.ingredients:
                lines.append("Ingredientes do usuário (o sistema calcula a compatibilidade): "
                             + ", ".join(self.ingredients) + ".")
        return " ".join(lines)


# ---------------------------------------------------------------- validação


def _grounded(term: str, question_words: list[str]) -> bool:
    """O termo extraído pelo LLM aparece (como sequência de palavras) no texto do usuário."""
    return bool(term.strip()) and lexicon.contains_term(question_words, term)


def _merge(user: list[str], mentioned: list[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for item in [*user, *mentioned]:
        item = " ".join(item.split())[:80]
        key = " ".join(lexicon.words(item))
        if item and key and key not in seen:
            seen.add(key)
            out.append(item)
    return tuple(out[:30])


def fallback_plan(c: ConsultationInput, reason: str) -> QueryPlan:
    intent: Intent = "recipes_by_ingredients" if c.available_ingredients else "recipes_by_characteristics"
    query = c.question if not c.available_ingredients else f"{c.question} {', '.join(c.available_ingredients)}"
    return QueryPlan(intent, query[:500], tuple(c.available_ingredients), None, "fallback", (reason,))


def validate_plan(raw: Any, c: ConsultationInput) -> QueryPlan:
    """Converte a saída do classificador num plano coerente com a consulta."""
    if not isinstance(raw, dict) or raw.get("intencao") not in LABELS:
        return fallback_plan(c, "invalid_classification")
    intent: Intent = LABELS[raw["intencao"]]
    corrections: list[str] = []
    q_words = lexicon.words(c.question)

    mentioned_raw = raw.get("ingredientes") if isinstance(raw.get("ingredientes"), list) else []
    mentioned = [m for m in mentioned_raw if isinstance(m, str) and _grounded(m, q_words)]
    if len(mentioned) < len(mentioned_raw):
        corrections.append("ungrounded_ingredients_dropped")
    ingredients = _merge(list(c.available_ingredients), mentioned)

    dish = raw.get("prato") if isinstance(raw.get("prato"), str) else ""
    dish = dish.strip() if _grounded(dish, q_words) else ""

    if intent == "list_categories" and ingredients:
        intent = "recipes_by_ingredients"  # quem informa ingredientes quer receitas
        corrections.append("categories_with_ingredients")
    if intent in NAME_INTENTS and not dish:
        intent = "recipes_by_ingredients" if ingredients else "recipes_by_characteristics"
        corrections.append("name_intent_without_dish")
    if intent == "recipes_by_ingredients" and not ingredients:
        intent = "recipes_by_characteristics"
        corrections.append("ingredient_intent_without_ingredients")

    query = raw.get("consulta") if isinstance(raw.get("consulta"), str) else ""
    query = " ".join(query.split())
    if intent in NAME_INTENTS:
        query = dish
    if len(query) < 3:
        query = c.question
    if ingredients and intent not in NAME_INTENTS and not all(lexicon.contains_term(lexicon.words(query), i)
                                                              for i in ingredients):
        query = f"{query} {', '.join(ingredients)}"
    return QueryPlan(intent, query[:500], ingredients, dish or None, "llm", tuple(corrections))


async def classify(llm: OllamaClient, c: ConsultationInput) -> tuple[QueryPlan, dict[str, Any]]:
    """Classifica com o LLM (saída estruturada) e valida. LLMError propaga (LLM indisponível)."""
    user = f"Pergunta: <<<{c.question}>>>"
    if c.available_ingredients:
        user += "\nIngredientes informados no formulário: " + ", ".join(c.available_ingredients)
    resp = await llm.chat([{"role": "system", "content": INTENT_PROMPT}, {"role": "user", "content": user}],
                          format=INTENT_SCHEMA)
    try:
        raw = json.loads(resp.content)
    except (json.JSONDecodeError, TypeError):
        raw = None
    plan = validate_plan(raw, c)
    trace = {"intent": plan.intent, "source": plan.source, "corrections": list(plan.corrections) or None,
             "duration_ms": round(resp.duration_ms)}
    return plan, trace
