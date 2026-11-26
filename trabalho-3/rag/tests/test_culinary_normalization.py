"""Teste I e normalização culinária (unitário, sem rede e sem fixture de corpus)."""
import pytest

from rag.ingredients import match_ingredients, normalize_ingredient as n, user_ingredient_keys


@pytest.mark.parametrize(("a", "b"), [
    ("Ovos", "ovo"), ("ÓVOS INTEIROS", "ovo"), ("pães", "pão"), ("Limões", "limão"), ("tomates maduros picados", "tomate"),
    ("queijo ralado", "queijo"), ("manteiga derretida", "manteiga"), ("cenouras médias raspadas", "cenoura"),
    ("Açúcar refinado", "açúcar"), ("maisena", "amido de milho"), ("fermento químico", "fermento em pó"),
    ("2 xícaras de farinha (peneirada)", "2 xícaras de farinha"), ("claras em neve", "clara de ovo"),
    ("batatas cozidas", "batata"), ("peito de frango cozido e desfiado", "peito de frango"),
    ("Mozzarella", "queijo mussarela"),
])
def test_equivalent_spellings_and_states(a, b):
    assert n(a) == n(b)


@pytest.mark.parametrize(("a", "b"), [
    ("leite", "leite condensado"), ("leite", "leite de coco"), ("leite", "creme de leite"), ("leite", "leite em pó"),
    ("farinha de trigo", "farinha de arroz"), ("farinha de trigo", "farinha de mandioca"),
    ("chocolate", "chocolate em pó"), ("coco", "coco ralado"), ("carne", "carne moída"),
    ("queijo", "queijo prato"), ("manteiga", "margarina"), ("polvilho doce", "polvilho azedo"),
])
def test_similar_but_different_ingredients_stay_different(a, b):
    assert n(a) != n(b)


def test_user_keys_cover_parts_and_generic_but_not_specific_varieties():
    assert n("gema de ovo") in user_ingredient_keys("ovos")
    assert n("peito de frango") in user_ingredient_keys("frango")
    assert n("queijo") in user_ingredient_keys("queijo parmesão")
    assert n("frango") in user_ingredient_keys("filé de frango")
    assert n("queijo parmesão") not in user_ingredient_keys("queijo")       # sem substituição presumida
    assert n("leite condensado") not in user_ingredient_keys("leite")
    assert n("chocolate em pó") not in user_ingredient_keys("chocolate")
    assert n("farinha de trigo") not in user_ingredient_keys("farinha")


def test_match_ingredients_uses_culinary_keys():
    entries = [
        {"name_original": "farinha de trigo", "name_normalized": n("farinha de trigo"), "alternatives_documented": [],
         "required": True},
        {"name_original": "gemas", "name_normalized": n("gemas"), "alternatives_documented": [], "required": True},
        {"name_original": "leite condensado", "name_normalized": n("leite condensado"), "alternatives_documented": [],
         "required": True},
    ]
    out = match_ingredients(entries, ["Ovos", "leite"])
    assert out["available_ingredients"] == ["gemas"]
    assert out["missing_ingredients"] == ["farinha de trigo", "leite condensado"]
