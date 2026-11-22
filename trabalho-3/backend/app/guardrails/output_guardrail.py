"""Guardrail de saída (prompts 23 e 25, docs/07-security/guardrails.md).

O LLM devolve só {status, answer, recipe_ids}. Cards, ingredientes, passos e fontes são montados
pelo backend a partir do evidence_set. Aqui se verifica se a NARRATIVA e os IDs escolhidos são
sustentados pelo que as ferramentas MCP retornaram neste turno.

Comparação de campos estruturados + heurísticas de texto: não é verificação semântica perfeita.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.guardrails import lexicon
from app.inference.evidence import EvidenceSet
from app.inference.system_prompt import SYSTEM_PROMPT
from app.schemas.query import ConsultationInput

MAX_ANSWER_CHARS = 2000

# ---------------------------------------------------------------- parse da resposta final


@dataclass(frozen=True)
class LLMFinal:
    status: str
    answer: str
    recipe_ids: tuple[str, ...]


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_final(content: str) -> LLMFinal | None:
    """Extrai o JSON final {status, answer, recipe_ids}. None se não houver JSON utilizável."""
    text = _FENCE_RE.sub("", content.strip())
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for cand in candidates:
        try:
            data: Any = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        status = data.get("status")
        answer = data.get("answer")
        ids = data.get("recipe_ids", [])
        if status not in ("FOUND", "INSUFFICIENT") or not isinstance(answer, str):
            continue
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            continue
        return LLMFinal(status=status, answer=answer, recipe_ids=tuple(ids))
    return None


# ---------------------------------------------------------------- extração de fatos verificáveis

_NUMBER_WORDS = {
    "um": "1", "uma": "1", "dois": "2", "duas": "2", "tres": "3", "quatro": "4", "cinco": "5", "seis": "6",
    "sete": "7", "oito": "8", "nove": "9", "dez": "10", "doze": "12", "quinze": "15", "vinte": "20",
    "trinta": "30", "quarenta": "40", "cinquenta": "50", "sessenta": "60", "noventa": "90", "cem": "100",
    "cento e oitenta": "180", "duzentos": "200", "meia": "0.5",
}
_NUM = r"(\d+(?:[.,]\d+)?|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")"
_FACT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("temperatura", re.compile(r"\b" + _NUM + r"\s*(?:°|º|graus?)\s*c?\b")),
    ("tempo", re.compile(r"\b" + _NUM + r"\s*(minut\w*|min\b|hor(?:a|as|inha|inhas)\b|hs?\b|segund\w*)")),
    ("porcoes", re.compile(r"\b(?:rende|serve|para)\s+" + _NUM + r"\s*(?:porc\w*|pessoas?|fatias?|unidades?|pedacos?)")),
    ("porcoes", re.compile(r"\b" + _NUM + r"\s*(?:porc(?:ao|oes)|pessoas|fatias)\b")),
    ("quantidade", re.compile(r"\b" + _NUM + r"\s*(g|kg|gramas?|ml|l|litros?|xicaras?|colheres?|copos?)\b")),
]

_UNIT_NORMAL = {"min": "minuto", "minutos": "minuto", "minuto": "minuto", "h": "hora", "hs": "hora",
                "horas": "hora", "hora": "hora", "segundos": "segundo", "segundo": "segundo",
                "g": "g", "gramas": "g", "grama": "g", "kg": "kg", "ml": "ml", "l": "l", "litros": "l",
                "litro": "l", "xicaras": "xicara", "xicara": "xicara", "colheres": "colher", "colher": "colher",
                "copos": "copo", "copo": "copo"}


def extract_facts(text: str) -> set[tuple[str, str, str]]:
    f = lexicon.fold(text)
    facts: set[tuple[str, str, str]] = set()
    for kind, pat in _FACT_PATTERNS:
        for m in pat.finditer(f):
            number = _NUMBER_WORDS.get(m.group(1), m.group(1)).replace(",", ".")
            raw_unit = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
            if raw_unit.startswith("minut"):
                raw_unit = "minuto"
            elif raw_unit.startswith("hor"):
                raw_unit = "hora"
            elif raw_unit.startswith("segund"):
                raw_unit = "segundo"
            unit = _UNIT_NORMAL.get(raw_unit, raw_unit)
            facts.add((kind, number, unit))
    return facts


_NUTRITION_RE = re.compile(
    r"\b(kcal|calorias?|caloric\w*|proteinas?|carboidratos?|gorduras?|lipidios?|fibras?|sodio|colesterol|"
    r"indice glicemico|vitaminas?|nutricion\w*|nutrientes?|emagrec\w*|saudavel|saudaveis|light|fit)\b"
)
_SAFETY_RE = re.compile(
    r"\b(seguro|segura|seguros|seguras|apto|apta|adequad\w*|recomendad\w*)\s+(para|pra)\s+"
    r"(alergic\w*|celiac\w*|intolerante\w*|criancas?|bebes?|gestantes?|gravidas?|diabetic\w*|"
    r"imunossuprimid\w*|todos)\b"
    r"|\b(sem|livre de|nao contem|isento de|isenta de)\s+(gluten|lactose|tracos|alergenic\w*|ovo|leite|"
    r"amendoim|castanhas?)\b"
    r"|\bhipoalergenic\w*\b|\b(pode|podem) (ser )?(comid\w*|consumid\w*|servid\w*) cru\w*"
    r"|\bnao (ha|tem|existe) risco\b|\bsem risco\b"
)
_SUBSTITUTION_RE = re.compile(r"\b(substitu\w*|trocar?\b.{0,30}\bpor\b|no lugar d[eoa]s?|em vez de|ao inves de)")
_URL_RE = re.compile(r"(https?://[^\s<>\"')\]]+|www\.[^\s<>\"')\]]+)", re.IGNORECASE)
_ID_RE = re.compile(r"\b[a-z]{2,10}-\d{2,}(?:-v\d+)?\b")
_STEP_LINE_RE = re.compile(r"^\s*(?:\d+\s*[.)\-:]|passo\s+\d+|[-*•])\s+(.+)$", re.IGNORECASE | re.MULTILINE)
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]+-----|"
    r"\bBearer\s+[A-Za-z0-9._-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})"
)
_LEAK_TERMS_RE = re.compile(r"\b(system prompt|prompt de sistema|prompt interno|minhas instrucoes internas)\b")
_HTML_RE = re.compile(r"<[^>]{0,200}>")


def _shingles(text: str, n: int = 8) -> set[tuple[str, ...]]:
    w = re.findall(r"[a-z0-9]+", lexicon.fold(text))
    return {tuple(w[i : i + n]) for i in range(len(w) - n + 1)}


_PROMPT_SHINGLES = _shingles(SYSTEM_PROMPT)


def _jaccard(a: str, b: str) -> float:
    sa, sb = set(lexicon.words(a)), set(lexicon.words(b))
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


# ---------------------------------------------------------------- verificação


@dataclass(frozen=True)
class OutputVerdict:
    ok: bool
    status: str
    answer: str
    recipe_ids: tuple[str, ...]
    violations: tuple[str, ...] = field(default_factory=tuple)


_READY_RE = re.compile(
    r"\b(?:(?:pode|podera|consegue|da para|da pra)\s+(?:ser\s+)?(?:prepar\w*|faz\w*|feit\w*)\s+(?:ja|agora)"
    r"|(?:ja|agora)\s+(?:pode|da para|da pra|consegue)\s+(?:prepar\w*|faz\w*)"
    r"|tem\s+(?:todos\s+os\s+ingredientes|tudo\s+(?:o\s+)?que\s+precisa))"
)


def sanitize_answer(answer: str) -> str:
    answer = _HTML_RE.sub("", answer)
    answer = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", answer).strip()
    return answer[:MAX_ANSWER_CHARS]


def check_text(answer: str, evidence: EvidenceSet, consultation: ConsultationInput,
               recipe_ids: tuple[str, ...]) -> list[str]:
    """Violações da narrativa frente ao evidence_set. Lista vazia = aprovada."""
    v: list[str] = []
    folded = lexicon.fold(answer)
    documented = evidence.documented_text()
    documented_folded = lexicon.fold(documented)

    # vazamento de prompt / segredos
    if _SECRET_RE.search(answer):
        v.append("SECRET_LEAK")
    if _LEAK_TERMS_RE.search(folded) or (_shingles(answer) & _PROMPT_SHINGLES):
        v.append("PROMPT_LEAK")

    # URLs e IDs fora do evidence_set
    allowed_urls = {u.rstrip("/.") for u in evidence.allowed_urls}
    for url in _URL_RE.findall(answer):
        if url.rstrip("/.,;") not in allowed_urls:
            v.append(f"UNSUPPORTED_URL:{url[:80]}")
    for rid in set(_ID_RE.findall(answer)):
        if rid not in evidence.allowed_ids:
            v.append(f"UNKNOWN_ID:{rid}")

    # números de tempo/temperatura/porções/quantidade não documentados
    doc_facts = extract_facts(documented)
    user_facts = extract_facts(consultation.question)
    for fact in sorted(extract_facts(answer) - doc_facts - user_facts):
        v.append(f"UNSUPPORTED_FACT:{fact[0]}={fact[1]}{fact[2]}")

    # nutrição e garantias de segurança alimentar (RN11)
    for m in _NUTRITION_RE.finditer(folded):
        if m.group(0) not in documented_folded:
            v.append(f"NUTRITION_CLAIM:{m.group(0)}")
            break
    for m in _SAFETY_RE.finditer(folded):
        if m.group(0) not in documented_folded:
            v.append(f"SAFETY_CLAIM:{m.group(0)[:40]}")
            break

    # substituições sem alternativa documentada (RN03)
    if _SUBSTITUTION_RE.search(folded):
        alts = {lexicon.fold(a) for a in evidence.alternatives()}
        if not alts or not any(a and a in folded for a in alts):
            v.append("UNDOCUMENTED_SUBSTITUTION")

    # ingredientes citados que não aparecem na evidência nem na pergunta do usuário
    allowed_words = set(lexicon.words(documented))
    for name in evidence.ingredient_names():
        allowed_words |= set(lexicon.words(name))
    allowed_words |= set(lexicon.words(consultation.question))
    for ing in consultation.available_ingredients:
        allowed_words |= set(lexicon.words(ing))
    answer_words = lexicon.words(answer)
    for food in sorted(lexicon.FOODS):
        if lexicon.contains_term(answer_words, food) and not set(lexicon.words(food)) <= allowed_words:
            v.append(f"UNSUPPORTED_INGREDIENT:{food}")

    # passos de preparo que não vêm da fonte
    steps = [m.group(1) for m in _STEP_LINE_RE.finditer(answer)]
    if len(steps) >= 2:
        canonical = [ins for d in evidence.documents.values() for ins in (d.get("instructions") or [])]
        for step in steps:
            if not any(_jaccard(step, c) >= 0.5 for c in canonical) and not _is_ingredient_line(step, evidence):
                v.append("UNDOCUMENTED_STEPS")
                break

    # "dá para preparar agora" quando nenhuma receita escolhida tem todos os ingredientes obrigatórios
    chosen = [evidence.hits[r] for r in recipe_ids if r in evidence.hits]
    if chosen and not any(h.compatibility == "COMPLETE" for h in chosen) and _READY_RE.search(folded):
        v.append("READINESS_CLAIM_WITHOUT_COMPLETE")

    # receita PARTIAL apresentada sem mencionar o que falta (RN05/HU04)
    for rid in recipe_ids:
        hit = evidence.hits.get(rid)
        if hit and hit.compatibility == "PARTIAL":
            missing = [lexicon.fold(m) for m in hit.missing_ingredients]
            if "falt" not in folded and not any(m in folded for m in missing):
                v.append(f"MISSING_NOT_MENTIONED:{rid}")
    return v


def _is_ingredient_line(line: str, evidence: EvidenceSet) -> bool:
    w = set(lexicon.words(line))
    return any(set(lexicon.words(n)) <= w for n in evidence.ingredient_names() if n)


def check_output(final: LLMFinal, evidence: EvidenceSet, consultation: ConsultationInput,
                 max_recipes: int = 5, *, topics_allowed: bool = True) -> OutputVerdict:
    """topics_allowed=False: a resposta precisa de receitas (pedido de receitas não se responde com categorias)."""
    violations: list[str] = []
    answer = sanitize_answer(final.answer)
    if not answer:
        violations.append("EMPTY_ANSWER")

    valid_ids: list[str] = []
    for rid in final.recipe_ids:
        if rid not in evidence.recipe_ids:
            violations.append(f"UNKNOWN_RECIPE_ID:{rid[:60]}")
        elif rid not in valid_ids:
            valid_ids.append(rid)
    valid_ids = valid_ids[:max_recipes]

    status = final.status
    if status == "FOUND" and not valid_ids and not (topics_allowed and evidence.topics):
        violations.append("FOUND_WITHOUT_EVIDENCE")
    if status == "INSUFFICIENT":
        valid_ids = []

    violations += check_text(answer, evidence, consultation, tuple(valid_ids))
    return OutputVerdict(ok=not violations, status=status, answer=answer, recipe_ids=tuple(valid_ids),
                         violations=tuple(violations))
