"""Validação da intenção e seleção programática das receitas (unitário, sem LLM e sem MCP).

[FIXTURE] A evidência é montada em memória com resultados sintéticos no formato do search_knowledge.
"""

import pytest

from app.inference.evidence import EvidenceSet
from app.inference.intent import QueryPlan, fallback_plan, validate_plan
from app.inference.recommend import name_score, select, template_answer
from app.integrations.mcp_client import ToolCallResult
from app.schemas.query import ConsultationInput


def consult(question, ingredients=()):
    return ConsultationInput(question=question, available_ingredients=list(ingredients))


def raw(intencao, prato="", ingredientes=(), consulta=""):
    return {"intencao": intencao, "prato": prato, "ingredientes": list(ingredientes), "consulta": consulta}


# ---------------------------------------------------------------- intenção


def test_ingredients_in_question_are_extracted_only_when_grounded():
    c = consult("Tenho ovos, queijo e tomate. O que posso fazer?")
    plan = validate_plan(raw("receitas_por_ingredientes", ingredientes=["ovos", "queijo", "tomate", "bacon"]), c)
    assert plan.intent == "recipes_by_ingredients" and plan.ingredients == ("ovos", "queijo", "tomate")
    assert "ungrounded_ingredients_dropped" in plan.corrections  # "bacon" não está na pergunta
    assert plan.ranking == "compatibility" and plan.tools == {"search_knowledge", "get_document"}


def test_categories_with_ingredients_becomes_recipe_search():
    plan = validate_plan(raw("listar_categorias"), consult("O que posso fazer no café da manhã?", ["pão", "ovo"]))
    assert plan.intent == "recipes_by_ingredients" and plan.required_tool == "search_knowledge"
    assert "list_topics" not in plan.tools


def test_real_categories_question_uses_list_topics_only():
    plan = validate_plan(raw("listar_categorias"), consult("Quais categorias de receitas vocês possuem?"))
    assert plan.intent == "list_categories" and plan.tools == {"list_topics"}


def test_name_intent_needs_a_dish_present_in_the_question():
    plan = validate_plan(raw("modo_de_preparo", prato="panqueca"), consult("Como preparo a panqueca encontrada?"))
    assert (plan.intent, plan.dish, plan.search_query, plan.ranking) == ("preparation", "panqueca", "panqueca", "relevance")
    invented = validate_plan(raw("receita_por_nome", prato="lasanha"), consult("Quero algo rápido para o café da manhã"))
    assert invented.intent == "recipes_by_characteristics" and invented.dish is None
    assert "name_intent_without_dish" in invented.corrections


def test_invalid_classification_falls_back_to_recipe_search():
    plan = validate_plan({"intencao": "outra"}, consult("Quero preparar algo doce", ["leite condensado"]))
    assert plan.source == "fallback" and plan.intent == "recipes_by_ingredients"
    assert fallback_plan(consult("Quero algo doce"), "x").intent == "recipes_by_characteristics"


def test_search_query_includes_user_ingredients():
    plan = validate_plan(raw("receitas_por_caracteristica", consulta="almoço"),
                         consult("Quero uma opção para o almoço", ["frango", "arroz"]))
    assert "frango" in plan.search_query and "arroz" in plan.search_query
    assert plan.search_arguments()["available_ingredients"] == ["frango", "arroz"]


# ---------------------------------------------------------------- seleção


def hit(rid, compat, missing=(), available=(), distance=0.5, title=None):
    return {"recipe_id": rid, "document_id": rid[:-3], "title": title or f"[FIXTURE] {rid}", "topic_key": "t",
            "source_url": f"https://example.org/{rid}", "source_excerpt": "", "compatibility": compat,
            "missing_ingredients": list(missing), "available_ingredients": list(available), "distance": distance}


def evidence(*hits):
    ev = EvidenceSet()
    ev.add(ToolCallResult("search_knowledge", {"evidence_status": "FOUND", "results": list(hits)}, 1.0))
    return ev


PLAN = QueryPlan("recipes_by_ingredients", "x", ("ovo", "leite"))


def test_complete_recipes_always_come_first_even_if_llm_skipped_them():
    ev = evidence(hit("p1-v1", "PARTIAL", ["farinha"], ["ovo"], 0.1), hit("c1-v1", "COMPLETE", [], ["ovo", "leite"], 0.9))
    sel = select(PLAN, ev, ("p1-v1",), 5)
    assert sel.recipe_ids == ("c1-v1", "p1-v1") and sel.situation == "CAN_PREPARE" and sel.changed


def test_partial_only_is_needs_ingredients_and_no_match_is_dropped():
    ev = evidence(hit("p1-v1", "PARTIAL", ["farinha", "açúcar"], ["ovo"], 0.1),
                  hit("p2-v1", "PARTIAL", ["farinha"], ["ovo", "leite"], 0.4),
                  hit("n1-v1", "NO_MATCH", ["chocolate"], [], 0.05))
    sel = select(PLAN, ev, ("n1-v1", "p1-v1", "p2-v1"), 5)
    assert sel.recipe_ids == ("p2-v1", "p1-v1")  # menos faltantes primeiro; NO_MATCH fora
    assert sel.situation == "NEEDS_INGREDIENTS"
    text = template_answer(PLAN, ev, sel)
    assert text.startswith("Não encontrei na base receitas que usem apenas os ingredientes informados.")
    assert "falta(m) farinha" in text and "dá para preparar" not in text


def test_name_search_filters_by_title():
    plan = QueryPlan("preparation", "panqueca", (), "panqueca")
    ev = evidence(hit("a-v1", "NOT_EVALUATED", title="Panqueca simples (versão 1)", distance=0.3),
                  hit("b-v1", "NOT_EVALUATED", title="Bolo de fubá", distance=0.1))
    sel = select(plan, ev, (), 5)
    assert sel.recipe_ids == ("a-v1",) and sel.situation == "NOT_EVALUATED"
    assert name_score("lagosta flambada", "Bolo de fubá") == 0
    assert name_score("bolo de cenoura", "Bolo de cenoura (versão 2)") > name_score("bolo de cenoura", "Bolo de fubá")


def test_characteristics_without_ingredients_respect_llm_insufficient():
    plan = QueryPlan("recipes_by_characteristics", "café da manhã", ())
    ev = evidence(hit("x-v1", "NOT_EVALUATED"))
    assert select(plan, ev, (), 5).recipe_ids == ()
    assert select(plan, ev, ("x-v1",), 5).recipe_ids == ("x-v1",)


@pytest.mark.parametrize("ids", [(), ("zzz-v1",)])
def test_nothing_eligible_is_none(ids):
    sel = select(PLAN, evidence(hit("n1-v1", "NO_MATCH")), ids, 5)
    assert sel.recipe_ids == () and sel.situation == "NONE"
