from rag.ingredients import match_ingredients, normalize_ingredient


def test_normalizes_aliases_without_equating_different_ingredients():
    assert normalize_ingredient("  ÓVOS ") == normalize_ingredient("ovo")
    assert normalize_ingredient("Farinha de trigo") != normalize_ingredient("farinha de aveia")
    assert normalize_ingredient("queijo") != normalize_ingredient("queijo prato")


def test_explicit_alternatives_and_optional_ingredients():
    entries = [
        {"name_original": "Manteiga", "name_normalized": "manteiga",
         "alternatives_documented": ["margarina"], "required": True},
        {"name_original": "Ovo", "name_normalized": "ovo", "alternatives_documented": [], "required": True},
        {"name_original": "Sal", "name_normalized": "sal", "alternatives_documented": [], "required": False},
    ]
    assert match_ingredients(entries, ["margarina", "ovos"])["compatibility"] == "COMPLETE"
    partial = match_ingredients(entries, ["margarina"])
    assert partial["compatibility"] == "PARTIAL"
    assert partial["missing_ingredients"] == ["Ovo"]
    assert partial["total_required"] == 2
    assert match_ingredients(entries, ["sal"])["compatibility"] == "INSUFFICIENT"
