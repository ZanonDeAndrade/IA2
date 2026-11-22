"""Normalização culinária de ingredientes (mesma regra na ingestão e na consulta via MCP).

`normalize_ingredient(nome)` produz uma chave canônica:
  1. minúsculas, sem acentos, sem pontuação e sem observações entre parênteses;
  2. singular por palavra (ovos -> ovo, pães -> pao, limões -> limao, colheres -> colher);
  3. remove modificadores de ESTADO, PREPARO e TAMANHO que não mudam o ingrediente
     (queijo ralado -> queijo, manteiga derretida -> manteiga, tomates maduros picados -> tomate);
  4. aplica sinônimos curados (maisena -> amido de milho, fermento químico -> fermento em pó).

Ingredientes diferentes continuam diferentes: leite ≠ leite condensado ≠ leite de coco ≠ creme de leite,
farinha de trigo ≠ farinha de arroz, chocolate ≠ chocolate em pó. Não há correspondência aproximada por texto.

`user_ingredient_keys(nome)` devolve as chaves de receita que o ingrediente informado pelo usuário satisfaz:
  - a própria chave;
  - partes do mesmo alimento (ovo -> gema de ovo, clara de ovo; frango -> peito/coxa/filé de frango);
  - o genérico de uma variedade (queijo parmesão satisfaz "queijo"; açúcar cristal satisfaz "açúcar").
O inverso NÃO vale: quem informa "queijo" não tem necessariamente "queijo parmesão" (sem substituições).
"""

import re
import unicodedata

# ---------------------------------------------------------------- texto


def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join(re.findall(r"[a-z0-9]+", decomposed.encode("ascii", "ignore").decode()))


_INVARIANT = {"ananas", "brocolis", "lapis", "pires", "mais", "menos", "tres", "seis", "dois", "gas", "atras", "jus",
              "cuscus", "xerez", "simples"}


def _singular(word: str) -> str:
    """Singular aproximado do português, aplicado igualmente aos dois lados da comparação."""
    if len(word) <= 3 or word in _INVARIANT or not word.endswith("s"):
        return word
    if word.endswith(("oes", "aes")):
        return word[:-3] + "ao"
    if word.endswith("eis") and len(word) > 4:
        return word[:-3] + "el"
    if word.endswith("ais") and len(word) > 4:
        return word[:-3] + "al"
    if word.endswith("ns"):
        return word[:-2] + "m"
    if word.endswith("es") and word[-3] in "rzs" and len(word) > 4:
        return word[:-2]
    if word.endswith(("ss", "us", "is")):
        return word
    return word[:-1]


# Modificadores de estado/preparo/tamanho (já no singular masculino e feminino).
_MODIFIERS = {
    "ralado", "ralada", "derretido", "derretida", "picado", "picada", "picadinho", "picadinha", "batido", "batida",
    "cozido", "cozida", "assado", "assada", "desfiado", "desfiada", "fatiado", "fatiada", "amassado", "amassada",
    "peneirado", "peneirada", "morno", "morna", "quente", "frio", "fria", "gelado", "gelada", "amolecido",
    "amolecida", "maduro", "madura", "fresco", "fresca", "grande", "medio", "media", "pequeno", "pequena",
    "inteiro", "inteira", "refinado", "refinada", "comum", "cru", "crua", "limpo", "limpa", "lavado", "lavada",
    "descascado", "descascada", "raspado", "raspada", "escorrido", "escorrida", "dessalgado", "dessalgada",
    "aferventado", "aferventada", "temperado", "temperada", "bem", "cheio", "cheia", "rasa", "raso",
    "grosso", "grossa", "fino", "fina", "amanhecido", "amanhecida", "dormido", "dormida",
}
_MODIFIER_PHRASES = ("em temperatura ambiente", "temperatura ambiente", "em cubo", "em cubinho", "em rodela",
                     "em fatia", "em pedaco", "em pedacinho", "em tira", "em neve", "sem casca", "sem semente",
                     "sem pele", "sem osso", "a gosto", "para untar", "para polvilhar", "para decorar", "ao gosto")
# Compostos em que o "modificador" faz parte da identidade do produto.
_PROTECTED = {"coco ralado", "pao ralado", "carne moida", "batata palha"}
_CONNECTORS = {"de", "da", "do", "e", "com", "sem", "em", "ou", "a", "o", "para"}


def _base_key(name: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", name)
    words = [_singular(w) for w in normalize_text(text).split()]
    key = " ".join(words)
    if key in _PROTECTED:
        return key
    for phrase in _MODIFIER_PHRASES:
        key = re.sub(rf"(^| ){phrase}( |$)", " ", key)
    words = [w for w in key.split() if w not in _MODIFIERS]
    while words and words[-1] in _CONNECTORS:
        words.pop()
    while words and words[0] in _CONNECTORS:
        words.pop(0)
    return " ".join(words)


# ---------------------------------------------------------------- sinônimos e relações curadas

_RAW_ALIASES = {
    "ovo de galinha": "ovo", "ovo caipira": "ovo",
    "gema": "gema de ovo", "clara": "clara de ovo",
    "fermento quimico": "fermento em po", "fermento quimico em po": "fermento em po",
    "fermento em po quimico": "fermento em po",
    "leite de vaca": "leite", "leite integral": "leite",
    "oleo de cozinha": "oleo", "oleo vegetal": "oleo",
    "manteiga sem sal": "manteiga", "manteiga com sal": "manteiga",
    "acucar branco": "acucar", "sal de cozinha": "sal", "sal fino": "sal", "agua filtrada": "agua",
    "farinha de trigo especial": "farinha de trigo", "farinha de trigo comum": "farinha de trigo",
    "pao ralado": "farinha de rosca",
    "batata inglesa": "batata",
    "maisena": "amido de milho", "maizena": "amido de milho",
    "mussarela": "queijo mussarela", "mucarela": "queijo mussarela", "mozarela": "queijo mussarela",
    "mozzarella": "queijo mussarela", "queijo mozarela": "queijo mussarela", "queijo mozzarella": "queijo mussarela",
    "queijo mucarela": "queijo mussarela", "parmesao": "queijo parmesao",
    "requeijao cremoso": "requeijao", "achocolatado em po": "achocolatado",
    "po royal": "fermento em po", "fermento em po royal": "fermento em po",
    "extrato de tomate": "extrato de tomate", "massa de tomate": "extrato de tomate",
}
ALIASES = {_base_key(k): _base_key(v) for k, v in _RAW_ALIASES.items()}

# Partes do mesmo alimento: quem tem o todo tem a parte.
_RAW_PARTS = {
    "ovo": ["gema de ovo", "clara de ovo"],
    "frango": ["peito de frango", "coxa de frango", "sobrecoxa de frango", "file de frango", "asa de frango",
               "frango em pedacos", "coxa e sobrecoxa de frango"],
}
# Variedades: quem tem a variedade tem o genérico (o inverso não).
_RAW_VARIETIES = {
    "queijo": ["queijo parmesao", "queijo mussarela", "queijo prato", "queijo minas", "queijo minas frescal",
               "queijo mineiro", "queijo branco", "queijo coalho", "queijo cheddar", "queijo provolone",
               "queijo gorgonzola", "queijo ricota", "ricota", "queijo canastra"],
    "acucar": ["acucar cristal", "acucar mascavo", "acucar demerara", "acucar de confeiteiro", "acucar refinado"],
    "oleo": ["oleo de soja", "oleo de girassol", "oleo de canola", "oleo de milho"],
    "farinha": ["farinha de trigo", "farinha de mandioca", "farinha de milho", "farinha de arroz", "farinha de rosca"],
    "pao": ["pao frances", "pao de forma", "pao italiano", "pao caseiro", "pao de leite", "pao sirio"],
    "pimenta": ["pimenta do reino", "pimenta calabresa", "pimenta dedo de moca"],
}


def normalize_ingredient(name: str) -> str:
    key = _base_key(name)
    return ALIASES.get(key, key)


PARTS = {normalize_ingredient(k): frozenset(normalize_ingredient(v) for v in vs) for k, vs in _RAW_PARTS.items()}
VARIETIES = {normalize_ingredient(k): frozenset(normalize_ingredient(v) for v in vs)
             for k, vs in _RAW_VARIETIES.items()}
_GENERIC_OF = {variety: generic for generic, vs in VARIETIES.items() for variety in vs}


def user_ingredient_keys(name: str) -> frozenset[str]:
    """Chaves de ingrediente de receita satisfeitas por um ingrediente que o usuário informou ter."""
    key = normalize_ingredient(name)
    if not key:
        return frozenset()
    keys = {key} | set(PARTS.get(key, ()))
    generic = _GENERIC_OF.get(key)
    if generic:
        keys.add(generic)
        keys |= PARTS.get(generic, frozenset())
    # corte de frango informado satisfaz "frango" genérico
    for whole, parts in PARTS.items():
        if key in parts:
            keys.add(whole)
    return frozenset(keys)


def match_ingredients(ingredients: list[dict], available: list[str]) -> dict:
    supplied: set[str] = set()
    for item in available:
        supplied |= user_ingredient_keys(item)
    present, missing = [], []
    for item in ingredients:
        if not item["required"]:
            continue
        names = {item.get("name_normalized") or normalize_ingredient(item["name_original"])}
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
