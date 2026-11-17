"""Corpus de receitas estruturadas do Wikilivros (pt.wikibooks.org, Livro de receitas, CC BY-SA 4.0).

É a fonte usada pelo servidor MCP: `data/normalized/recipes.json` (receitas com ingredientes e passos) e um
índice Chroma persistente com embeddings MiniLM multilíngues (384d). O RAG de PDFs (`rag.retrieve`) continua
separado e inalterado.

    python -m rag.wikibooks collect   # baixa o wikitext + revid de cada página para data/raw/wikibooks/
    python -m rag.wikibooks build     # normaliza -> recipes.json, chunking, embeddings, Chroma
    python -m rag.wikibooks query "ovos e queijo"

Contrato com o MCP (mcp-server/store.py): `retrieve(query, top_k, topic_key) -> list[dict]` com
chunk_id, recipe_id, document_id, text, distance e metadata.section.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from .embed import MODEL_NAME, MODEL_REVISION, Embedder
from .ingredients import normalize_ingredient

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "wikibooks"
RECIPES_JSON = ROOT / "data" / "normalized" / "recipes.json"
CHROMA_DIR = ROOT / "data" / "chroma_wikibooks"
COLLECTION = "wikibooks_recipes_minilm_v1"
API = "https://pt.wikibooks.org/w/api.php"
LICENSE = "CC BY-SA 4.0 (Wikilivros)"
USER_AGENT = "assistente-receitas-academico/0.1 (trabalho de IA II)"

# Páginas reais do Livro de receitas. As 5 primeiras são as planejadas em docs (seção 07).
PAGES: dict[str, str] = {
    "Livro de receitas/Brigadeiro": "sobremesas",
    "Livro de receitas/Panqueca simples": "massas",
    "Livro de receitas/Omelete com queijo": "ovos",
    "Livro de receitas/Arroz-doce": "sobremesas",
    "Livro de receitas/Bolo de cenoura": "bolos",
    "Livro de receitas/Pudim de leite": "sobremesas",
    "Livro de receitas/Bolinhos de queijo": "salgados",
    "Livro de receitas/Pão de queijo mineiro": "salgados",
    "Livro de receitas/Bolo de fubá": "bolos",
    "Livro de receitas/Bolo de chocolate": "bolos",
    "Livro de receitas/Torta salgada": "salgados",
    "Livro de receitas/Croquetes de frango": "salgados",
    "Livro de receitas/Panqueca de mel": "massas",
    "Livro de receitas/Broinha de farinha de trigo": "paes",
    "Livro de receitas/Caçarola simples": "sobremesas",
    "Livro de receitas/Bolo salgado": "salgados",
}
TOPIC_LABELS = {"sobremesas": "Sobremesas", "massas": "Massas e panquecas", "ovos": "Ovos", "bolos": "Bolos",
                "salgados": "Salgados", "paes": "Pães e broas"}


# ---------------------------------------------------------------- coleta


def _api(params: dict) -> dict:
    url = f"{API}?{urllib.parse.urlencode({**params, 'format': 'json', 'formatversion': 2})}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def collect() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    have = {json.loads(p.read_text(encoding="utf-8"))["title"] for p in RAW_DIR.glob("*.json")}
    for title in PAGES:
        if title in have:
            continue
        try:
            data = _api({"action": "parse", "page": title, "prop": "wikitext|revid", "redirects": 1})
        except OSError as exc:  # 429/rede: segue com as demais; rodar collect de novo completa
            print(f"FALHOU {title}: {exc}", file=sys.stderr)
            time.sleep(2)
            continue
        if "parse" not in data:
            print(f"IGNORADA (não encontrada): {title}", file=sys.stderr)
            continue
        p = data["parse"]
        out = {"title": p["title"], "pageid": p["pageid"], "revid": p["revid"], "wikitext": p["wikitext"],
               "retrieved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
        (RAW_DIR / f"{p['pageid']}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"ok {p['title']} rev={p['revid']}")
        time.sleep(0.3)


# ---------------------------------------------------------------- limpeza e normalização

_LINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
_HEADING = re.compile(r"^(={2,4})\s*(.*?)\s*\1\s*$")
_QTY = re.compile(
    r"^(?P<qty>(?:\d+[\d/,.½¼¾]*|meia|meio|uma?|duas|dois|tr[eê]s|quatro|cinco|seis)\b"
    r"(?:\s+e\s+\d+/\d+|\s+e\s+meia|\s+a\s+\d+)?"
    r"(?:\s+prato\s+(?:fundo|raso|cheio)|\s+[a-zçãéêíóú]+\.?)?(?:\s*\([^)]*\))?(?:\s+de\s+(?:sopa|chá|cha|café))?(?:\s*\([^)]*\))?)"
    r"\s*(?:de|da|do|das|dos)?\s+(?P<name>.+)$",
    re.IGNORECASE,
)
_A_GOSTO = re.compile(r"^(?P<name>.+?)\s+(?P<qty>a gosto|[àa] vontade|q\.?b\.?|quanto baste)$", re.IGNORECASE)
# qualificadores entre a medida e o "de" ("bem cheia", "rasa", "copo grande") atrapalham separar quantidade e nome
_QUALIFIER = re.compile(r"\s*,?\s*\b(?:bem chei[ao]s?|ras[ao]s?|até derramando)\b\s*,?", re.IGNORECASE)
_BIG_UNIT = re.compile(r"\b(copos?|xícaras?)\s+grandes?\s*", re.IGNORECASE)


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = _TEMPLATE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = text.replace("'''", "").replace("''", "")
    return " ".join(text.split()).strip(" ;.")


_UNITS = {"xícara", "xícaras", "xicara", "xicaras", "colher", "colheres", "copo", "copos", "lata", "latas",
          "pitada", "pitadas", "g", "kg", "ml", "l", "litro", "litros", "pacote", "pacotes", "tablete", "dente",
          "dentes", "fatia", "fatias", "unidade", "unidades", "gramas", "grama", "vidro", "frasco", "caixa",
          "caixinha", "envelope", "maço", "punhado", "pedaço", "pedaços", "cálice", "concha", "gema", "gemas",
          "clara", "claras", "mL"}


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
            # "3 ovos": o "unidade" capturado é o próprio ingrediente
            if len(words) == 2 and words[1].lower().strip(".") not in _UNITS and " de " not in text[: len(qty_part) + 4]:
                qty_part, rest = words[0], f"{words[1]} {rest}".strip()
            qty, name = qty_part, rest
    # nome principal: corta observações ("ou", "para", vírgula, parênteses)
    base = re.split(r"\s+(?:ou|para|bem|em|a gosto)\s+|\s+a\s+\d|,|\(|;", name, maxsplit=1)[0].strip(" .:")
    base = re.sub(r"\s+(?:grandes?|pequen[oa]s?|médi[oa]s?)$", "", base)
    notes = name[len(base):].strip(" ,.;") or None
    required = not re.search(r"opcional|a gosto|para decorar|para untar|polvilhar", text, re.IGNORECASE)
    return {
        "name_original": base or name,
        "name_normalized": normalize_ingredient(base or name),
        "quantity_text": qty,
        "required": required,
        "notes": notes,
        "alternatives_documented": [],
    }


def _sections(wikitext: str) -> list[tuple[list[str], list[str]]]:
    """Retorna [(caminho de títulos, linhas)] na ordem do documento."""
    out: list[tuple[list[str], list[str]]] = []
    path: list[str] = []
    lines: list[str] = []
    for raw in wikitext.splitlines():
        m = _HEADING.match(raw.strip())
        if m:
            out.append((list(path), lines))
            level = len(m.group(1)) - 2
            path = path[:level] + [clean(m.group(2))]
            lines = []
        else:
            lines.append(raw)
    out.append((list(path), lines))
    return out


def _kind(heading: str) -> str | None:
    h = heading.lower()
    if h.startswith("ingrediente"):
        return "ingredients"
    if any(k in h for k in ("preparo", "modo de fazer", "como fazer", "preparação", "instru")):
        return "instructions"
    return None


def parse_page(raw: dict, topic_key: str) -> list[dict]:
    """Uma receita por variante ("Receita 1", "Receita 2"...) com ingredientes e passos próprios."""
    variants: dict[str, dict[str, list[str]]] = {}
    order: list[str] = []
    for path, lines in _sections(raw["wikitext"]):
        if not path:
            continue
        kind = _kind(path[-1])
        if kind is None:
            continue
        variant = " / ".join(path[:-1]) or "principal"
        if variant not in variants:
            variants[variant] = {"ingredients": [], "instructions": []}
            order.append(variant)
        for line in lines:
            s = line.strip()
            if kind == "ingredients" and s.startswith("*"):
                item = clean(s.lstrip("*#: "))
                if item and not item.endswith(":"):
                    variants[variant][kind].append(item)
            elif kind == "instructions" and (s.startswith("#") or s.startswith("*") or (s and not s.startswith(("[[", "{{")))):
                step = clean(s.lstrip("*#: "))
                if len(step) > 3:
                    variants[variant][kind].append(step)

    page_title = raw["title"].split("/", 1)[-1]
    slug = re.sub(r"[^a-z0-9]+", "-", normalize_ingredient(page_title)).strip("-")
    document_id = f"wb-{raw['pageid']}"
    url_title = urllib.parse.quote(raw["title"].replace(" ", "_"), safe="/:")
    recipes = []
    usable = [v for v in order if variants[v]["ingredients"] and variants[v]["instructions"]]
    for idx, variant in enumerate(usable, start=1):
        parts = variants[variant]
        title = page_title if len(usable) == 1 else f"{page_title} ({variant})"
        recipes.append({
            "recipe_id": f"{document_id}-{slug}-v{idx}"[:128],
            "document_id": document_id,
            "variant_index": idx,
            "title": title,
            "topic_key": topic_key,
            "topic_label": TOPIC_LABELS.get(topic_key, topic_key),
            "ingredients": [parse_ingredient(i) for i in parts["ingredients"]],
            "instructions": parts["instructions"],
            "source_url": f"https://pt.wikibooks.org/wiki/{url_title}",
            "revision_url": f"https://pt.wikibooks.org/w/index.php?oldid={raw['revid']}",
            "license": LICENSE,
            "retrieved_at": raw["retrieved_at"],
        })
    return recipes


# ---------------------------------------------------------------- chunking, embeddings e índice


def chunks_for(recipe: dict) -> list[dict]:
    """Dois chunks curtos por receita (a janela do MiniLM é curta): sinopse+ingredientes e preparo."""
    names = ", ".join(i["name_original"] for i in recipe["ingredients"])
    steps = " ".join(recipe["instructions"])
    base = {"recipe_id": recipe["recipe_id"], "document_id": recipe["document_id"], "topic_key": recipe["topic_key"]}
    return [
        {**base, "chunk_id": f"{recipe['recipe_id']}-c0", "section": "ingredients",
         "text": f"{recipe['title']}. Ingredientes: {names}."},
        {**base, "chunk_id": f"{recipe['recipe_id']}-c1", "section": "instructions",
         "text": f"{recipe['title']}. Modo de preparo: {steps}"[:1200]},
    ]


def _collection(create: bool = False):
    from chromadb import PersistentClient
    from chromadb.config import Settings

    client = PersistentClient(path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False))
    if create:
        try:
            client.delete_collection(COLLECTION)
        except Exception:  # noqa: BLE001 - coleção ainda não existe
            pass
        return client.create_collection(
            COLLECTION, metadata={"hnsw:space": "cosine", "embedding_model": MODEL_NAME, "embedding_revision": MODEL_REVISION}
        )
    return client.get_collection(COLLECTION)


def build(offline: bool = False) -> dict:
    raws = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RAW_DIR.glob("*.json"))]
    if not raws:
        raise SystemExit("Nenhuma página em data/raw/wikibooks/. Rode: python -m rag.wikibooks collect")
    recipes: list[dict] = []
    for raw in raws:
        recipes.extend(parse_page(raw, PAGES.get(raw["title"], "outros")))
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
    col.add(
        ids=[c["chunk_id"] for c in chunks],
        embeddings=vectors,
        documents=[c["text"] for c in chunks],
        metadatas=[{k: c[k] for k in ("recipe_id", "document_id", "topic_key", "section")} for c in chunks],
    )
    report = {"documents": len(raws), "recipes": len(recipes), "chunks": col.count(),
              "embedding_model": MODEL_NAME, "dimension": len(vectors[0])}
    (CHROMA_DIR / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


# ---------------------------------------------------------------- recuperação (contrato do MCP)

_EMBEDDER: Embedder | None = None
_COLLECTION = None

# Palavras genéricas de pergunta que não indicam um prato ou ingrediente.
_GENERIC = {
    "receita", "receitas", "preparar", "preparo", "fazer", "faco", "posso", "tenho", "quero", "como", "algo", "estes",
    "esses", "essas", "estas", "ingrediente", "ingredientes", "prato", "pratos", "comida", "cozinhar", "sugestao",
    "sugira", "qual", "quais", "voce", "voces", "para", "com", "sem", "uma", "um", "que", "dos", "das", "nos", "nas",
    "tem", "existe", "existem", "simples", "facil", "rapido", "rapida", "gostaria", "favor", "sobre",
}


def _terms(text: str) -> set[str]:
    words = normalize_ingredient(text).split()
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words if len(w) > 2 and w not in _GENERIC}


def _relevant(query_terms: set[str], text: str) -> bool:
    """Recuperação híbrida: além da proximidade vetorial, o trecho precisa citar algum termo da consulta.

    O MiniLM aproxima textos de culinária mesmo sem relação (ex.: "lagosta flambada" → brigadeiro); sem este
    filtro o LLM receberia evidência irrelevante em vez de uma busca vazia (INSUFFICIENT).
    """
    return bool(query_terms & _terms(text)) if query_terms else True


def retrieve(query: str, top_k: int = 8, topic_key: str | None = None) -> list[dict]:
    """Busca semântica top-k no Chroma. Usada pelo servidor MCP (RAG_RETRIEVER=rag.wikibooks:retrieve)."""
    global _EMBEDDER, _COLLECTION
    if _EMBEDDER is None:
        _EMBEDDER = Embedder(offline=True)
    if _COLLECTION is None:
        _COLLECTION = _collection()
    vector = _EMBEDDER.encode([query], truncate=True)[0]
    k = max(1, min(int(top_k), 20))
    res = _COLLECTION.query(
        query_embeddings=[vector],
        n_results=min(k * 4, _COLLECTION.count()),
        where={"topic_key": topic_key} if topic_key else None,
    )
    hits = []
    query_terms = _terms(query)
    for cid, doc, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0], strict=True):
        hits.append({"chunk_id": cid, "recipe_id": meta["recipe_id"], "document_id": meta["document_id"],
                     "text": doc, "distance": float(dist), "metadata": dict(meta)})
    return [h for h in hits if _relevant(query_terms, h["text"])][:k]


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
        print(json.dumps(build(offline=args.offline), ensure_ascii=False))
    else:
        for h in retrieve(args.text, top_k=args.top_k):
            print(f"{h['distance']:.3f} {h['recipe_id']} [{h['metadata']['section']}] {h['text'][:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
