import re
import unicodedata

ALIASES = {
    "ovos": "ovo",
    "cenouras": "cenoura",
    "leite de vaca": "leite",
    "gemas": "gema de ovo",
    "gema": "gema de ovo",
    "gemas de ovos": "gema de ovo",
    "fermento quimico": "fermento em po",
}


def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join(re.findall(r"[a-z0-9]+", decomposed.encode("ascii", "ignore").decode()))


def normalize_ingredient(name: str) -> str:
    normalized = normalize_text(name)
    return ALIASES.get(normalized, normalized)


def match_ingredients(ingredients: list[dict], available: list[str]) -> dict:
    supplied = {normalize_ingredient(item) for item in available}
    present, missing = [], []
    for item in ingredients:
        if not item["required"]:
            continue
        names = {item["name_normalized"]}
        names.update(normalize_ingredient(name) for name in item["alternatives_documented"])
        (present if names & supplied else missing).append(item["name_original"])

    status = "COMPLETE" if not missing else "PARTIAL" if present else "INSUFFICIENT"
    return {
        "compatibility": status,
        "available_ingredients": present,
        "missing_ingredients": missing,
        "matched_required": len(present),
        "total_required": len(present) + len(missing),
    }
