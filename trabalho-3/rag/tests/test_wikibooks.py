"""Parser do corpus Wikilivros (sem rede). O índice real é verificado por scripts/real_eval.py."""
from rag.wikibooks import _sample, chunks_for, parse_ingredient, parse_ingredients, parse_page, topic_of

WIKITEXT = """{{Navegação|[[Livro de receitas/Índice|<<< Índice]]|[[Livro de receitas/Índice/Doces/Panquecas|Panquecas >>>]]}}
[[Imagem:x.jpg|thumb|foto]]
== Receita 1 ==
=== Ingredientes ===
* 2 xícaras (chá)de farinha de trigo;
* 3 ovos;
* 1 colher (sopa), rasa, de sal;
=== Preparo ===
# Bata os ovos.
# Acrescente a [[farinha]] e o '''sal'''.
== Receita 2 ==
=== Ingredientes ===
* 1 pitada de sal
* 1 xícara de leite
=== Preparo ===
# Misture.
{{AutoCat}}
"""

# Formato "Ingredientes e Preparo" com pseudo-cabeçalho (Pudim de leite, Omelete com queijo...)
COMBINED = """== Omelete com queijo - 1 ==
==='''Ingredientes e Preparo:'''===
* 2 ovos --
* 1/2 xícara (chá) de queijo prato, ralado;
* 4 colheres (sopa) de chocolate em pó
* Sal e pimenta-do-reino

:'''Preparo:'''
# Bata os ovos e junte os demais ingredientes.
# Derreta a manteiga.
"""


def raw(text, title="Livro de receitas/Panqueca simples", pageid=12129):
    return {"title": title, "pageid": pageid, "revid": 1, "wikitext": text, "retrieved_at": "2026-11-16T00:00:00Z"}


def test_parse_ingredient_quantities_and_names():
    assert parse_ingredient("2 xícaras (chá)de farinha de trigo;")["name_original"] == "farinha de trigo"
    egg = parse_ingredient("2 ovos grandes ou 4 pequenos;")
    assert (egg["quantity_text"], egg["name_original"], egg["name_normalized"]) == ("2", "ovos", "ovo")
    assert parse_ingredient("1 colher (sopa) bem cheia, até derramando, de farinha de trigo;")["name_original"] == "farinha de trigo"
    salt = parse_ingredient("Sal a gosto")
    assert (salt["name_original"], salt["quantity_text"], salt["required"]) == ("Sal", "a gosto", False)
    assert parse_ingredient("4 colheres (sopa) de chocolate em pó")["name_normalized"] == "chocolate em po"
    assert parse_ingredient("1&nbsp;xícara de leite")["name_original"] == "leite"
    assert parse_ingredient("Farinha de trigo até o ponto de enrolar")["name_original"] == "Farinha de trigo"
    assert [i["name_normalized"] for i in parse_ingredients("Sal e pimenta-do-reino")] == ["sal", "pimenta do reino"]


def test_parse_page_one_recipe_per_variant_with_source_and_topic():
    recipes = parse_page(raw(WIKITEXT))
    assert [r["recipe_id"] for r in recipes] == ["wb-12129-panqueca-simples-v1", "wb-12129-panqueca-simples-v2"]
    assert [r["title"] for r in recipes] == ["Panqueca simples (versão 1)", "Panqueca simples (versão 2)"]
    first = recipes[0]
    assert [i["name_normalized"] for i in first["ingredients"]] == ["farinha de trigo", "ovo", "sal"]
    assert first["instructions"] == ["Bata os ovos", "Acrescente a farinha e o sal"]
    assert first["source_url"] == "https://pt.wikibooks.org/wiki/Livro_de_receitas/Panqueca_simples"
    assert first["revision_url"].endswith("oldid=1") and "CC BY-SA" in first["license"]
    assert (first["topic_key"], first["topic_label"], first["subcategory"]) == ("doces", "Doces", "Panquecas")
    assert [c["section"] for c in chunks_for(first)] == ["ingredients", "instructions"]
    assert "(Doces › Panquecas)" in chunks_for(first)[0]["text"]


def test_combined_ingredients_and_steps_layout():
    [r] = parse_page(raw(COMBINED, "Livro de receitas/Omelete com queijo", 9725))
    assert r["title"] == "Omelete com queijo"
    assert [i["name_normalized"] for i in r["ingredients"]] == [
        "ovo", "queijo prato", "chocolate em po", "sal", "pimenta do reino"]
    assert r["instructions"] == ["Bata os ovos e junte os demais ingredientes", "Derreta a manteiga"]


def test_topic_fallback_uses_dish_category():
    assert topic_of("[[Categoria:Panquecas]] [[Categoria:Leite, receitas com]]") == (
        "outras-receitas", "Outras receitas", "Panquecas")


def test_uniform_sample_is_deterministic():
    items = [f"p{i:03d}" for i in range(100)]
    assert _sample(items, 5) == ["p000", "p025", "p050", "p074", "p099"]
    assert _sample(items[:3], 5) == items[:3]


def test_optional_markers_only_apply_to_the_main_clause():
    """Regressão (avaliação real): 'se quiser' era da alternativa e tornava a sardinha opcional -> falso COMPLETE."""
    sardinha = parse_ingredient("1 lata de sardinha (ou de atum, se quiser) --")
    assert sardinha["required"] is True and sardinha["name_normalized"] == "sardinha"
    assert parse_ingredient("1 xícara de nozes (opcional)")["required"] is False
    assert parse_ingredient("queijo ralado para polvilhar")["required"] is False


def test_preparation_and_size_words_leave_the_name():
    assert parse_ingredient("2 pratos fundos de feijão bem cozido")["name_original"] == "feijão"
    assert parse_ingredient("1 vidro pequeno de leite de coco")["name_original"] == "leite de coco"
    batata = parse_ingredient("4 batatas cozidas e picadas em rodelas grossas")
    assert (batata["name_original"], batata["notes"]) == ("batatas", "cozidas e picadas em rodelas grossas")
    assert parse_ingredient("100 g de coco ralado")["name_normalized"] == "coco ralado"


def test_wikipedia_link_templates_keep_the_word_and_relative_navigation_gives_topic():
    assert parse_ingredient("2 {{w|abobrinhas}} picadas;")["name_original"] == "abobrinhas"
    assert parse_ingredient("1 envelope de {{w|caldo de legumes|caldo}}")["name_original"] == "caldo"
    nav = "{{Navegação|[[../|<<< Índice]]|[[../Pratos Principais e Variados|<<<]]|[[../Verduras e Legumes|>>>]]}}"
    assert topic_of(nav)[1] == "Pratos Principais e Variados"


def test_no_dangling_connector_at_the_end_of_the_name():
    assert parse_ingredient("2 ovos inteiros e batidos")["name_original"] == "ovos inteiros"
