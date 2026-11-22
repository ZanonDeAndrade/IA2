"""Corpus de receitas estruturadas do Wikilivros (pt.wikibooks.org, Livro de receitas, CC BY-SA 4.0).

É a fonte usada pelo servidor MCP: `data/normalized/recipes.json` (receitas com ingredientes e passos) e um
índice Chroma persistente com embeddings MiniLM multilíngues (384d). O RAG de PDFs (`rag.retrieve`) continua
separado e inalterado.

    python -m rag.wikibooks collect   # páginas-semente + categorias "X, receitas com" -> data/raw/wikibooks/
    python -m rag.wikibooks build     # normaliza -> recipes.json, chunking, embeddings, Chroma
    python -m rag.wikibooks query "ovos e queijo"

Contrato com o MCP (mcp-server/store.py): `retrieve(query, top_k, topic_key) -> list[dict]` com
chunk_id, recipe_id, document_id, text, distance e metadata.section. A recuperação aqui é só semântica;
compatibilidade de ingredientes e ranking ficam no servidor MCP (search_knowledge).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path

from .embed import MODEL_NAME, MODEL_REVISION, Embedder
from .ingredients import normalize_ingredient, normalize_text

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "wikibooks"
MANIFEST = RAW_DIR / "_manifest.json"
RECIPES_JSON = ROOT / "data" / "normalized" / "recipes.json"
CHROMA_DIR = ROOT / "data" / "chroma_wikibooks"
COLLECTION = "wikibooks_recipes_minilm_v2"
API = "https://pt.wikibooks.org/w/api.php"
LICENSE = "CC BY-SA 4.0 (Wikilivros)"
USER_AGENT = "assistente-receitas-academico/0.2 (trabalho de IA II)"
PREFIX = "Livro de receitas/"

# As 5 primeiras são os documentos planejados em docs (seção 07).
SEED_PAGES = [
    "Livro de receitas/Brigadeiro", "Livro de receitas/Panqueca simples", "Livro de receitas/Omelete com queijo",
    "Livro de receitas/Arroz-doce", "Livro de receitas/Bolo de cenoura", "Livro de receitas/Pudim de leite",
    "Livro de receitas/Bolinhos de queijo", "Livro de receitas/Pão de queijo mineiro", "Livro de receitas/Bolo de fubá",
    "Livro de receitas/Bolo de chocolate",
]
# Categorias de ingrediente do próprio Wikilivros e quantas páginas (amostra uniforme, determinística) usar de cada.
SEED_CATEGORIES = {
    "Ovo, receitas com": 45, "Queijo, receitas com": 35, "Tomate, receitas com": 30, "Frango, receitas com": 35,
    "Arroz, receitas com": 25, "Batata, receitas com": 30, "Cenoura, receitas com": 20, "Pão, receitas com": 20,
    "Leite condensado, receitas com": 25, "Manteiga, receitas com": 20, "Leite, receitas com": 20,
    "Farinha de trigo, receitas com": 25, "Carne moída, receitas com": 15, "Macarrão, receitas com": 15,
    "Feijão, receitas com": 10, "Banana, receitas com": 10,
}
REQUEST_INTERVAL = 2.0  # segundos entre requisições (a API do Wikimedia limita clientes agressivos)


# ---------------------------------------------------------------- coleta


def _api(params: dict, *, retries: int = 6) -> dict:
    url = f"{API}?{urllib.parse.urlencode({**params, 'format': 'json', 'formatversion': 2})}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.load(resp)
            time.sleep(REQUEST_INTERVAL)
            return data
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == retries - 1:
                raise
            wait = int(exc.headers.get("Retry-After") or 0) or 15 * (attempt + 1)
            print(f"  limite de requisições (429); aguardando {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("inalcançável")


def _sample(items: list[str], cap: int) -> list[str]:
    """Amostra uniforme e determinística ao longo da lista ordenada (evita viés alfabético)."""
    if len(items) <= cap:
        return items
    return [items[round(i * (len(items) - 1) / (cap - 1))] for i in range(cap)]


def _category_titles(category: str) -> list[str]:
    data = _api({"action": "query", "list": "categorymembers", "cmtitle": f"Categoria:{category}",
                 "cmnamespace": 0, "cmlimit": 500})
    titles = [m["title"] for m in data.get("query", {}).get("categorymembers", [])]
    return sorted(t for t in titles if t.startswith(PREFIX) and "Índice" not in t and "Imprimir" not in t)


def collect() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    have = {json.loads(p.read_text(encoding="utf-8"))["title"] for p in RAW_DIR.glob("*.json") if p != MANIFEST}
    selected: OrderedDict[str, list[str]] = OrderedDict((t, ["semente"]) for t in SEED_PAGES)
    for category, cap in SEED_CATEGORIES.items():
        titles = _category_titles(category)
        print(f"{category}: {len(titles)} páginas, usando {min(cap, len(titles))}")
        for t in _sample(titles, cap):
            selected.setdefault(t, []).append(category)

    pending = [t for t in selected if t not in have]
    print(f"{len(selected)} páginas selecionadas, {len(pending)} a baixar")
    retrieved_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i in range(0, len(pending), 50):
        batch = pending[i: i + 50]
        data = _api({"action": "query", "prop": "revisions", "rvprop": "ids|content", "rvslots": "main",
                     "titles": "|".join(batch), "redirects": 1})
        for page in data.get("query", {}).get("pages", []):
            if page.get("missing") or not page.get("revisions"):
                continue
            rev = page["revisions"][0]
            text = rev["slots"]["main"]["content"]
            if text.lstrip().upper().startswith("#REDIRECT"):
                continue
            out = {"title": page["title"], "pageid": page["pageid"], "revid": rev["revid"], "wikitext": text,
                   "retrieved_at": retrieved_at}
            (RAW_DIR / f"{page['pageid']}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                            encoding="utf-8")
        print(f"  lote {i // 50 + 1}: {len(batch)} títulos")
    MANIFEST.write_text(json.dumps({
        "fonte": "pt.wikibooks.org, Livro de receitas", "licenca": LICENSE,
        "criterio": "páginas-semente + amostra uniforme de categorias 'X, receitas com' (SEED_CATEGORIES)",
        "categorias": SEED_CATEGORIES, "paginas": selected, "atualizado_em": retrieved_at,
    }, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- limpeza

_LINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
# {{w|abobrinhas}} / {{w|alvo|rótulo}}: links para a Wikipédia/Wikcionário dentro do texto -> mantém a palavra
_LINK_TEMPLATE = re.compile(r"\{\{\s*(?:w|wp|wikt|wikipédia|wikipedia)\s*\|([^{}|]*)(?:\|([^{}]*))?\}\}", re.IGNORECASE)
_HEADING = re.compile(r"^(={2,5})\s*(.*?)\s*\1\s*$")
_QTY = re.compile(
    r"^(?P<qty>(?:\d+[\d/,.½¼¾]*|meia|meio|uma?|duas|dois|tr[eê]s|quatro|cinco|seis)\b"
    r"(?:\s+e\s+\d+/\d+|\s+e\s+meia|\s+a\s+\d+)?"
    r"(?:\s+pratos?\s+(?:fundos?|rasos?|cheios?)|\s+[a-zçãéêíóú]+\.?(?:\s+(?:pequen|grand|médi)[a-z]*)?)?"
    r"(?:\s*\([^)]*\))?"
    r"(?:\s+de\s+(?:sopa|chá|cha|café))?(?:\s*\([^)]*\))?)"
    r"\s*(?:de|da|do|das|dos)?\s+(?P<name>.+)$",
    re.IGNORECASE,
)
_A_GOSTO = re.compile(r"^(?P<name>.+?)\s+(?P<qty>a gosto|[àa] vontade|q\.?b\.?|quanto baste)$", re.IGNORECASE)
# qualificadores entre a medida e o "de" ("bem cheia", "rasa", "copo grande") atrapalham separar quantidade e nome
_QUALIFIER = re.compile(r"\s*,?\s*\b(?:bem chei[ao]s?|chei[ao]s?|ras[ao]s?|até derramando)\b\s*,?", re.IGNORECASE)
_BIG_UNIT = re.compile(r"\b(copos?|xícaras?)\s+grandes?\s*", re.IGNORECASE)
_UNITS = {"xícara", "xícaras", "xicara", "xicaras", "colher", "colheres", "copo", "copos", "lata", "latas",
          "pitada", "pitadas", "g", "kg", "ml", "l", "litro", "litros", "pacote", "pacotes", "tablete", "dente",
          "dentes", "fatia", "fatias", "unidade", "unidades", "gramas", "grama", "vidro", "frasco", "caixa",
          "caixinha", "envelope", "maço", "punhado", "pedaço", "pedaços", "cálice", "concha", "mililitros",
          "garrafa", "pedacinho", "kilo", "quilo", "gr", "lt", "tabletes", "latinha", "pote", "ramo", "talo",
          "folhas", "folha", "cabeça", "posta", "postas", "filés", "pé", "chávena", "chávenas", "chavena", "chavenas"}


def clean(text: str) -> str:
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", "", text)
    text = _LINK_TEMPLATE.sub(lambda m: (m.group(2) or m.group(1)).strip(), text)
    for _ in range(3):  # templates aninhados
        text = _TEMPLATE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r"\s*--+\s*$", "", text)
    return " ".join(text.split()).strip(" ;.:-–")


def parse_ingredient(line: str) -> dict:
    text = clean(line)
    text = _BIG_UNIT.sub(r"\1 ", _QUALIFIER.sub(" ", text)).strip()
    qty: str | None = None
    name = text
    m = _A_GOSTO.match(text)
    if m:
        name, qty = m.group("name"), m.group("qty")
    else:
        m = _QTY.match(text)
        if m:
            qty_part, rest = m.group("qty").strip(), m.group("name").strip()
            words = qty_part.split()
            # "3 ovos", "2 ovos grandes": a "unidade" capturada é o próprio ingrediente
            if (len(words) >= 2 and words[1].lower().strip(".") not in _UNITS | {"e", "a"}
                    and not words[1][0].isdigit() and not words[1].startswith("(")
                    and " de " not in text[: len(qty_part) + 4]):
                qty_part, rest = words[0], f"{' '.join(words[1:])} {rest}".strip()
            qty, name = qty_part, rest
    # nome principal: corta observações ("ou ...", "para ...", vírgula, parênteses). "em pó" faz parte do nome.
    base = re.split(r"\s+(?:ou|para|a gosto)\s+|\s+a\s+\d|,|\(|;|\.\s|\s+[-–]\s+|"
                    r"\s+(?:até|o suficiente|o necessário|o quanto|que d[êe]|quanto)\b", name, maxsplit=1)[0].strip(" .:")
    # "batatas cozidas e picadas em rodelas": o modo de preparo vai para as observações ("ralado" fica: coco ralado)
    base = re.split(r"\s+(?:bem\s+)?(?:cozid|picad|cortad|descascad|passad|amassad|batid|derretid|fatiad|lavad|desfiad|"
                    r"escorrid|peneirad|dissolvid)[a-z]*\b", base, maxsplit=1)[0]
    base = re.sub(r"\s+(?:grandes?|pequen[oa]s?|médi[oa]s?)$", "", base)
    base = re.sub(r"(?:\s+(?:e|de|com|bem))+$", "", base)  # "ovos inteiros e" (batidos)
    notes = name[len(base):].strip(" ,.;-–") or None
    # "opcional" vale em qualquer lugar; marcadores fracos só na oração principal (fora de parênteses e de "ou ...":
    # em "sardinha (ou atum, se quiser)" o "se quiser" é da alternativa, não da sardinha)
    head = re.split(r"\(|\s+ou\s+", text, maxsplit=1)[0]
    required = not (re.search(r"opcional|facultativ", text, re.IGNORECASE) or re.search(
        r"a gosto|à vontade|a vontade|para decorar|para untar|polvilhar|se quiser|se desejar|q\.?b\.?", head,
        re.IGNORECASE))
    return {
        "name_original": base or name,
        "name_normalized": normalize_ingredient(base or name),
        "quantity_text": qty,
        "required": required,
        "notes": notes,
        "alternatives_documented": [],
    }


def parse_ingredients(line: str) -> list[dict]:
    """Uma linha pode listar mais de um item sem quantidade ("Sal e pimenta-do-reino", "Canela em pó e sal")."""
    first = parse_ingredient(line)
    text = clean(line)
    if first["quantity_text"] is None and re.search(r"\s+e\s+", text) and len(text.split()) <= 8:
        parts = [p for p in re.split(r"\s+e\s+", text) if p.strip()]
        if len(parts) > 1:
            items = [parse_ingredient(p) for p in parts]
            for it in items:
                it["required"] = it["required"] and first["required"]
            return items
    return [first]


# ---------------------------------------------------------------- estrutura da página


def _kind(heading: str) -> str | None:
    h = normalize_text(heading)
    has_ing = h.startswith("ingrediente") or " ingrediente" in f" {h}"
    has_steps = any(k in h for k in ("preparo", "modo de fazer", "como fazer", "preparacao", "confeccao",
                                     "instruc", "modo de preparar", "procedimento"))
    if has_ing and has_steps:
        return "both"
    if has_ing:
        return "ingredients"
    if has_steps:
        return "instructions"
    return None


_PSEUDO_HEADING = re.compile(r"^[:;]*\s*(?:'''|<b>)?\s*([^*#].{0,60}?)\s*:?\s*(?:'''|</b>)?\s*:?\s*$")
_META_PORTIONS = re.compile(r"^(?:rendimento|rende|porç(?:ões|ao|ão)|serve)\s*:?\s*((?:\d|aproximadamente|cerca).{0,58})$",
                            re.IGNORECASE)
_META_TIME = re.compile(r"^tempo(?: de (?:preparo|preparação|cozimento))?\s*:?\s*((?:\d|aproximadamente|cerca|meia|uma).{0,58})$",
                        re.IGNORECASE)
_NAV = re.compile(r"\[\[(?:Livro de receitas/Índice/|\.\./)([^|\]]+)")
_DISH_CATEGORY = re.compile(r"\[\[Categoria:([^|\]]+)")


def topic_of(wikitext: str) -> tuple[str, str, str | None]:
    """(topic_key, topic_label, subcategoria) a partir da navegação documentada da página no Wikilivros."""
    paths = [[seg for seg in p.split("/") if seg.strip()] for p in _NAV.findall(wikitext)]
    paths = [p for p in paths if p]
    if paths:
        path = max(paths, key=len)
        label = path[0].strip()
        sub = path[-1].strip() if len(path) > 1 else None
    else:
        dish = [c.strip() for c in _DISH_CATEGORY.findall(wikitext) if "receitas com" not in c.lower()]
        label, sub = "Outras receitas", (dish[0] if dish else None)
    key = re.sub(r"[^a-z0-9]+", "-", normalize_text(label)).strip("-") or "outras-receitas"
    return key, label, sub


def _variant_title(page_title: str, label: str, multiple: bool) -> str:
    if label == "principal" or not multiple:
        return page_title
    m = re.search(r"(?:receita|vers[ãa]o|modo|op[çc][ãa]o)?\s*[-–]?\s*(\d+)\s*$", label, re.IGNORECASE)
    if m:
        return f"{page_title} (versão {m.group(1)})"
    if normalize_text(label) == normalize_text(page_title):
        return page_title
    return f"{page_title} – {label}"


def parse_page(raw: dict, topic: tuple[str, str, str | None] | None = None) -> list[dict]:
    """Uma receita por variante (seção de nível 2), com ingredientes e passos próprios."""
    wikitext = raw["wikitext"]
    topic_key, topic_label, sub = topic or topic_of(wikitext)
    variants: OrderedDict[str, dict] = OrderedDict()
    current = "principal"
    mode: str | None = None

    def bucket() -> dict:
        return variants.setdefault(current, {"ingredients": [], "instructions": [], "portions": None, "time": None})

    for raw_line in wikitext.splitlines():
        s = raw_line.strip()
        if not s:
            continue
        h = _HEADING.match(s)
        if h:
            title = clean(h.group(2))
            kind = _kind(title)
            if kind is not None:
                mode = kind
            elif len(h.group(1)) == 2:
                current, mode = title or "principal", None
            else:
                mode = None  # subseção (Massa, Recheio...): o próximo cabeçalho/pseudo-cabeçalho define o modo
            continue
        marked = s.startswith((":", ";", "<b>", "\'\'\'")) or s.endswith(":")
        if marked and not s.startswith(("*", "#")) and len(s) <= 70:
            p = _PSEUDO_HEADING.match(s)
            if p and _kind(clean(p.group(1))):
                mode = _kind(clean(p.group(1)))
                continue
        plain = clean(s.lstrip("*#:; "))
        if not plain:
            continue
        if (m := _META_PORTIONS.match(plain)) and not bucket()["portions"]:
            bucket()["portions"] = m.group(1)
            continue
        if (m := _META_TIME.match(plain)) and not bucket()["time"]:
            bucket()["time"] = m.group(1)
            continue
        if s.startswith(("*", "#")):
            if plain.endswith(":") or len(plain) < 2:
                continue  # rótulo de componente ("Massa:")
            if mode == "ingredients" or (mode == "both" and s.startswith("*")):
                bucket()["ingredients"].append(plain)
            elif mode in ("instructions", "both"):
                bucket()["instructions"].append(plain)
        elif mode == "instructions" and not s.startswith(("[[", "{{", "|", "!", "<")) and len(plain) > 15:
            bucket()["instructions"].append(plain)

    page_title = raw["title"].split("/", 1)[-1]
    slug = re.sub(r"[^a-z0-9]+", "-", normalize_text(page_title)).strip("-")[:60]
    document_id = f"wb-{raw['pageid']}"
    url_title = urllib.parse.quote(raw["title"].replace(" ", "_"), safe="/:")
    usable = [(k, v) for k, v in variants.items() if len(v["ingredients"]) >= 2 and v["instructions"]]
    recipes = []
    for idx, (label, parts) in enumerate(usable, start=1):
        recipes.append({
            "recipe_id": f"{document_id}-{slug}-v{idx}"[:128],
            "document_id": document_id,
            "variant_index": idx,
            "title": _variant_title(page_title, label, len(usable) > 1),
            "topic_key": topic_key,
            "topic_label": topic_label,
            "subcategory": sub,
            "ingredients": [ing for line in parts["ingredients"] for ing in parse_ingredients(line)
                            if ing["name_normalized"]],
            "instructions": parts["instructions"],
            "portions": parts["portions"],
            "preparation_time": parts["time"],
            "source_url": f"https://pt.wikibooks.org/wiki/{url_title}",
            "revision_url": f"https://pt.wikibooks.org/w/index.php?oldid={raw['revid']}",
            "license": LICENSE,
            "retrieved_at": raw["retrieved_at"],
        })
    return recipes


# ---------------------------------------------------------------- chunking, embeddings e índice


def chunks_for(recipe: dict) -> list[dict]:
    """Dois chunks curtos por receita (a janela do MiniLM é de 128 tokens): ingredientes e preparo.

    A categoria documentada entra no texto para que buscas como "algo doce" ou "prato principal" a alcancem.
    """
    names = ", ".join(i["name_original"] for i in recipe["ingredients"])
    steps = " ".join(recipe["instructions"])
    category = recipe["topic_label"] + (f" › {recipe['subcategory']}" if recipe.get("subcategory") else "")
    base = {"recipe_id": recipe["recipe_id"], "document_id": recipe["document_id"], "topic_key": recipe["topic_key"]}
    return [
        {**base, "chunk_id": f"{recipe['recipe_id']}-c0", "section": "ingredients",
         "text": f"{recipe['title']} ({category}). Ingredientes: {names}."},
        {**base, "chunk_id": f"{recipe['recipe_id']}-c1", "section": "instructions",
         "text": f"{recipe['title']}. Modo de preparo: {steps}"[:1200]},
    ]


def _collection(create: bool = False):
    from chromadb import PersistentClient
    from chromadb.config import Settings

    client = PersistentClient(path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False))
    if create:
        for col in client.list_collections():
            client.delete_collection(col.name if hasattr(col, "name") else col)
        return client.create_collection(
            COLLECTION, metadata={"hnsw:space": "cosine", "embedding_model": MODEL_NAME, "embedding_revision": MODEL_REVISION}
        )
    return client.get_collection(COLLECTION)


def load_raw() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RAW_DIR.glob("*.json")) if p != MANIFEST]


def build(offline: bool = False) -> dict:
    raws = load_raw()
    if not raws:
        raise SystemExit("Nenhuma página em data/raw/wikibooks/. Rode: python -m rag.wikibooks collect")
    recipes: list[dict] = []
    skipped: list[str] = []
    for raw in sorted(raws, key=lambda r: r["title"]):
        parsed = parse_page(raw)
        recipes.extend(parsed)
        if not parsed:
            skipped.append(raw["title"])
    RECIPES_JSON.parent.mkdir(parents=True, exist_ok=True)
    RECIPES_JSON.write_text(json.dumps({
        "_fonte": "Wikilivros, Livro de receitas (pt.wikibooks.org), CC BY-SA 4.0. Créditos: histórico de cada página "
                  "(revision_url). Adaptação: texto limpo de marcação wiki; uma receita por variante.",
        "recipes": recipes,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    chunks = [c for r in recipes for c in chunks_for(r)]
    embedder = Embedder(offline=offline)
    vectors = embedder.encode([c["text"] for c in chunks], truncate=True)
    col = _collection(create=True)
    for i in range(0, len(chunks), 500):
        part = chunks[i: i + 500]
        col.add(
            ids=[c["chunk_id"] for c in part],
            embeddings=vectors[i: i + 500],
            documents=[c["text"] for c in part],
            metadatas=[{k: c[k] for k in ("recipe_id", "document_id", "topic_key", "section")} for c in part],
        )
    topics: dict[str, int] = {}
    for r in recipes:
        topics[r["topic_label"]] = topics.get(r["topic_label"], 0) + 1
    report = {"documents": len(raws), "documents_without_recipe": len(skipped), "recipes": len(recipes),
              "chunks": col.count(), "topics": topics, "embedding_model": MODEL_NAME, "dimension": len(vectors[0]),
              "skipped_titles": skipped}
    (CHROMA_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


# ---------------------------------------------------------------- recuperação (contrato do MCP)

_EMBEDDER: Embedder | None = None
_COLLECTION = None


def retrieve(query: str, top_k: int = 8, topic_key: str | None = None) -> list[dict]:
    """Busca semântica top-k (cosseno) no Chroma. Usada pelo MCP (RAG_RETRIEVER=rag.wikibooks:retrieve)."""
    global _EMBEDDER, _COLLECTION
    if _EMBEDDER is None:
        _EMBEDDER = Embedder(offline=True)
    if _COLLECTION is None:
        _COLLECTION = _collection()
    vector = _EMBEDDER.encode([query], truncate=True)[0]
    k = max(1, min(int(top_k), 200, _COLLECTION.count()))
    res = _COLLECTION.query(query_embeddings=[vector], n_results=k,
                            where={"topic_key": topic_key} if topic_key else None)
    return [
        {"chunk_id": cid, "recipe_id": meta["recipe_id"], "document_id": meta["document_id"], "text": doc,
         "distance": float(dist), "metadata": dict(meta)}
        for cid, doc, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0],
                                        strict=True)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m rag.wikibooks")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("collect")
    b = sub.add_parser("build")
    b.add_argument("--offline", action="store_true")
    q = sub.add_parser("query")
    q.add_argument("text")
    q.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if args.cmd == "collect":
        collect()
    elif args.cmd == "build":
        report = build(offline=args.offline)
        print(json.dumps({k: v for k, v in report.items() if k != "skipped_titles"}, ensure_ascii=False))
    else:
        for h in retrieve(args.text, top_k=args.top_k):
            print(f"{h['distance']:.3f} {h['recipe_id']} [{h['metadata']['section']}] {h['text'][:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
