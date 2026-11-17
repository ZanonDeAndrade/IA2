"""Parser do corpus Wikilivros (sem rede). O índice real é verificado por scripts/real_e2e.py."""
from rag.wikibooks import chunks_for, parse_ingredient, parse_page

WIKITEXT = """[[Imagem:x.jpg|thumb|foto]]
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
=== Preparo ===
# Misture.
{{AutoCat}}
"""


def test_parse_ingredient_quantities_and_names():
    assert parse_ingredient("2 xícaras (chá)de farinha de trigo;")["name_original"] == "farinha de trigo"
    egg = parse_ingredient("2 ovos grandes ou 4 pequenos;")
    assert (egg["quantity_text"], egg["name_original"], egg["name_normalized"]) == ("2", "ovos", "ovo")
    assert parse_ingredient("1 colher (sopa) bem cheia, até derramando, de farinha de trigo;")["name_original"] == "farinha de trigo"
    salt = parse_ingredient("Sal a gosto")
    assert (salt["name_original"], salt["quantity_text"], salt["required"]) == ("Sal", "a gosto", False)


def test_parse_page_one_recipe_per_variant_with_source():
    raw = {"title": "Livro de receitas/Panqueca simples", "pageid": 12129, "revid": 1, "wikitext": WIKITEXT,
           "retrieved_at": "2026-11-16T00:00:00Z"}
    recipes = parse_page(raw, "massas")
    assert [r["recipe_id"] for r in recipes] == ["wb-12129-panqueca-simples-v1", "wb-12129-panqueca-simples-v2"]
    first = recipes[0]
    assert [i["name_normalized"] for i in first["ingredients"]] == ["farinha de trigo", "ovo", "sal"]
    assert first["instructions"] == ["Bata os ovos", "Acrescente a farinha e o sal"]
    assert first["source_url"] == "https://pt.wikibooks.org/wiki/Livro_de_receitas/Panqueca_simples"
    assert first["revision_url"].endswith("oldid=1") and "CC BY-SA" in first["license"]
    assert [c["section"] for c in chunks_for(first)] == ["ingredients", "instructions"]


def test_relevance_filter_requires_a_shared_term():
    from rag.wikibooks import _relevant, _terms

    assert _terms("Tenho ovos e farinha. O que posso preparar?") == {"ovos", "farinha"}
    assert _relevant(_terms("receita de brigadeiro"), "Brigadeiro (Receita 7). Modo de preparo: mexa")
    assert not _relevant(_terms("Como preparar lagosta flambada?"), "Brigadeiro. Ingredientes: leite condensado")
    assert _relevant(_terms("O que posso preparar?"), "qualquer trecho")  # sem termos: só o vetor decide
