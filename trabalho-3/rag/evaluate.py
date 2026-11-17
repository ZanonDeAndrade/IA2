"""Executa as consultas rotuladas e registra métricas e candidatos reais do Chroma."""
import argparse
import json
import platform
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

from .ingest import json_bytes, replace_file
from .retrieve import Retriever
from .vector_store import DEFAULT_DATA, ROOT

DEFAULT_CASES = ROOT / "tests" / "fixtures" / "rag_queries.json"


def evaluate(retriever: Retriever, cases: list[dict]) -> dict:
    rows = []
    expected_pages = returned_pages = 0
    hits = total_expected = relevant = returned = cited = negatives = abstentions = 0
    for case in cases:
        expected = set(case["expected_recipe_ids"])
        if expected - retriever.recipes.keys():
            raise ValueError(f"IDs desconhecidos no gabarito: {case['id']}")
        start = perf_counter()
        result = retriever.search(
            case["query"], case.get("available_ingredients"), case.get("topic_key"),
            top_k=8, include_trace=True,
        )
        duration = perf_counter() - start
        candidate_ids = {chunk["recipe_id"] for chunk in result["trace"]}
        results = {item["recipe_id"]: item for item in result["results"]}
        if expected:
            total_expected += 1
            hits += bool(expected & candidate_ids)
            expected_pages += len(expected)
            returned_pages += len(expected & results.keys())
        else:
            negatives += 1
            abstentions += result["evidence_status"] == "INSUFFICIENT"
        relevant += len(expected & results.keys())
        returned += len(results)
        cited += sum(
            bool(item["source_url"]) and item["source_url"] == retriever.recipes[recipe_id]["source_url"]
            for recipe_id, item in results.items()
        )
        rows.append({
            **case,
            "duration_ms": round(duration * 1000, 2),
            **result,
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            **{name: version(name) for name in ("chromadb", "sentence-transformers", "torch", "transformers")},
        },
        "index": {"collection": retriever.collection.name, **retriever.collection.metadata},
        "metrics": {
            "queries": len(cases),
            "recall_at_8": hits / total_expected if total_expected else None,
            "expected_pages_returned": f"{returned_pages}/{expected_pages}",
            "precision_at_5": relevant / returned if returned else None,
            "source_coverage": cited / returned if returned else None,
            "negative_abstentions": f"{abstentions}/{negatives}",
        },
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--chroma-path", type=Path, default=DEFAULT_DATA / "chroma")
    parser.add_argument("--recipes", type=Path, default=DEFAULT_DATA / "normalized" / "recipes.json")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    retriever = Retriever(args.chroma_path, args.recipes, offline=args.offline)
    if not retriever.recipes:
        parser.exit(1, "Corpus vazio. Execute a ingestão.\n")
    report = evaluate(retriever, json.loads(args.cases.read_text(encoding="utf-8")))
    if args.output:
        replace_file(args.output, json_bytes(report))
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
