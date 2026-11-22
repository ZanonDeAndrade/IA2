"""Compatibilidade e ranking do search_knowledge (Testes A, B, I e J).

[FIXTURE] Receitas sintéticas controladas e um retriever falso em memória: aqui se testa a LÓGICA de
compatibilidade e ordenação (função pura `tools.search_knowledge`), não a qualidade do índice real.
A normalização usada é a real (`rag.ingredients`).
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rag.ingredients import normalize_ingredient, user_ingredient_keys  # noqa: E402
from store import Hit, RecipeStore  # noqa: E402
from tools import ToolContext, compute_compatibility, search_knowledge  # noqa: E402


def recipe(rid, title, ingredients, optional=(), topic="testes"):
    ings = [{"name_original": i, "name_normalized": normalize_ingredient(i), "required": True} for i in ingredients]
    ings += [{"name_original": i, "name_normalized": normalize_ingredient(i), "required": False} for i in optional]
    return {"recipe_id": rid, "document_id": rid.rsplit("-", 1)[0], "title": f"[FIXTURE] {title}",
            "topic_key": topic, "topic_label": topic.capitalize(), "ingredients": ings,
            "instructions": ["Passo de teste."], "source_url": f"https://example.org/{rid}"}


CORPUS = [
    recipe("t-omelete-v1", "Omelete de queijo e tomate", ["ovos", "queijo ralado", "tomates picados"], ["sal"]),
    recipe("t-panqueca-v1", "Panqueca", ["ovo", "farinha de trigo", "leite", "açúcar"]),
    recipe("t-pudim-v1", "Pudim", ["leite condensado", "leite", "ovos"]),
    recipe("t-brigadeiro-v1", "Brigadeiro", ["leite condensado", "chocolate em pó", "manteiga"]),
    recipe("t-pao-ovo-v1", "Pão com ovo", ["pão francês", "ovo", "manteiga"]),
    recipe("t-torrada-v1", "Torrada", ["pão", "manteiga"]),
    recipe("t-frango-v1", "Frango com batata", ["peito de frango", "batatas", "cenoura", "arroz"]),
    recipe("t-bolo-arroz-v1", "Bolo de farinha de arroz", ["farinha de arroz", "ovo", "açúcar"]),
]


class FakeRetriever:
    """Devolve chunks na ordem de `ranking` (distâncias crescentes); simula o índice semântico."""

    def __init__(self, ranking):
        self.ranking = ranking

    def search(self, query, top_k, topic_key):
        hits = [Hit(chunk_id=f"{rid}-c0", recipe_id=rid, document_id=rid.rsplit("-", 1)[0], text=f"trecho {rid}",
                    distance=0.1 * (i + 1), section="ingredients") for i, rid in enumerate(self.ranking)]
        return hits[:top_k], 0


@pytest.fixture
def ctx(tmp_path):
    path = tmp_path / "recipes.json"
    path.write_text(json.dumps({"recipes": CORPUS}, ensure_ascii=False), encoding="utf-8")

    def make(semantic_order):
        return ToolContext(store=RecipeStore(path), retriever=FakeRetriever(semantic_order),
                           normalize=normalize_ingredient, user_keys=user_ingredient_keys)
    return make


def by_id(out):
    return {r.recipe_id: r for r in out.results}


# ---------------------------------------------------------------- Teste A: compatibilidade completa
def test_a_complete_when_all_required_present(ctx):
    out = search_knowledge(ctx(["t-omelete-v1"]), "o que posso fazer", ["Ovo", "queijo", "tomate", "pão"], None, 5)
    om = by_id(out)["t-omelete-v1"]
    assert om.compatibility == "COMPLETE" and om.missing_ingredients == []  # sal é opcional
    assert out.results[0].recipe_id == "t-omelete-v1" and out.ranking == "compatibility"


# ---------------------------------------------------------------- Teste B: compatibilidade parcial
def test_b_partial_lists_missing_flour_and_sugar(ctx):
    out = search_knowledge(ctx(["t-panqueca-v1"]), "receita", ["ovo", "leite"], None, 5)
    pan = by_id(out)["t-panqueca-v1"]
    assert pan.compatibility == "PARTIAL"
    assert pan.missing_ingredients == ["farinha de trigo", "açúcar"]
    assert pan.available_ingredients == ["ovo", "leite"]


# ---------------------------------------------------------------- Teste I: ingredientes semelhantes
@pytest.mark.parametrize(("user", "rid", "missing"), [
    (["leite", "chocolate", "manteiga"], "t-brigadeiro-v1", ["leite condensado", "chocolate em pó"]),
    (["farinha de trigo", "ovo", "açúcar"], "t-bolo-arroz-v1", ["farinha de arroz"]),
    (["leite", "ovos"], "t-pudim-v1", ["leite condensado"]),
])
def test_i_similar_ingredients_are_not_equivalent(ctx, user, rid, missing):
    r = ctx([]).store.snapshot().recipes[rid]
    comp = compute_compatibility(r, user, normalize_ingredient, user_ingredient_keys)
    assert comp.missing == missing and comp.status == "PARTIAL"


def test_i_cream_is_not_milk(ctx):
    r = ctx([]).store.snapshot().recipes["t-pudim-v1"]
    comp = compute_compatibility(r, ["creme de leite", "leite condensado", "ovo"], normalize_ingredient,
                                 user_ingredient_keys)
    assert comp.missing == ["leite"]


def test_parts_and_varieties(ctx):
    snap = ctx([]).store.snapshot().recipes
    frango = compute_compatibility(snap["t-frango-v1"], ["frango", "arroz", "batata", "cenoura"], normalize_ingredient,
                                   user_ingredient_keys)
    assert frango.status == "COMPLETE"  # peito de frango é parte do frango informado; batatas -> batata
    pao = compute_compatibility(snap["t-pao-ovo-v1"], ["pão", "ovo", "manteiga"], normalize_ingredient,
                                user_ingredient_keys)
    assert pao.missing == ["pão francês"]  # "pão" genérico não garante "pão francês" (sem substituição)


# ---------------------------------------------------------------- Teste J: ranking
def test_j_ranking_is_lexicographic_and_documented(ctx):
    # índice semântico (falso) coloca o brigadeiro e o bolo de arroz no topo; o ranking por compatibilidade não
    # deixa a similaridade textual passar na frente de quem dá para preparar.
    semantic = ["t-brigadeiro-v1", "t-bolo-arroz-v1", "t-panqueca-v1", "t-torrada-v1", "t-pao-ovo-v1",
                "t-omelete-v1", "t-pudim-v1", "t-frango-v1"]
    out = search_knowledge(ctx(semantic), "café da manhã", ["pão", "manteiga", "ovo", "queijo"], None, 5)
    order = [r.recipe_id for r in out.results]
    # 1º COMPLETE (torrada); depois PARTIAL com 1 faltante, mais ingredientes do usuário primeiro
    # (pão com ovo usa ovo+manteiga; omelete usa ovo+queijo -> empate, decide a distância semântica);
    # depois 2 faltantes; brigadeiro (manteiga) e bolo de arroz (ovo) também têm 2 faltantes, decide a distância.
    assert order[0] == "t-torrada-v1"
    assert order[1:3] == ["t-pao-ovo-v1", "t-omelete-v1"]
    assert [r.compatibility for r in out.results][:1] == ["COMPLETE"]
    missing_counts = [len(r.missing_ingredients) for r in out.results]
    assert missing_counts == sorted(missing_counts)


def test_j_no_match_excluded_and_structured_candidates_included(ctx):
    # o índice só devolve o brigadeiro (sem ingrediente em comum); o frango vem pelo critério estruturado
    out = search_knowledge(ctx(["t-brigadeiro-v1"]), "almoço", ["frango", "arroz", "batata", "cenoura"], None, 5)
    assert [r.recipe_id for r in out.results] == ["t-frango-v1"]
    assert out.results[0].matched_chunks == [] and out.results[0].distance is None


def test_g_no_overlap_is_insufficient(ctx):
    out = search_knowledge(ctx(["t-brigadeiro-v1", "t-pudim-v1"]), "lagosta", ["lagosta", "trufa negra"], None, 5)
    assert out.evidence_status == "INSUFFICIENT" and out.results == []


def test_relevance_mode_keeps_semantic_order_and_reports_compatibility(ctx):
    out = search_knowledge(ctx(["t-brigadeiro-v1", "t-pudim-v1"]), "brigadeiro", ["ovo"], None, 5, "relevance")
    assert [r.recipe_id for r in out.results] == ["t-brigadeiro-v1", "t-pudim-v1"]
    assert [r.compatibility for r in out.results] == ["NO_MATCH", "PARTIAL"] and out.ranking == "relevance"
