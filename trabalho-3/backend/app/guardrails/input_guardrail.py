"""Guardrail de entrada (prompt 24, docs/07-security/guardrails.md).

Roda ANTES de qualquer contato com LLM ou MCP. Ordem:
  1. formato e tipos (objeto JSON com question: str e available_ingredients: list[str])
  2. limpeza e limites (tamanho, quantidade, caracteres de controle, marcação HTML)
  3. prompt injection (heurística: não é a única defesa)
  4. escopo culinário (bloqueia só pedidos explicitamente fora do domínio)

A mensagem devolvida ao usuário é genérica: não revela qual regra disparou.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from app.guardrails import lexicon
from app.schemas.query import ConsultationInput
from app.settings import Settings

InputCode = Literal["INPUT_INVALID", "OUT_OF_SCOPE", "PROMPT_INJECTION"]

MESSAGES: dict[str, str] = {
    "INPUT_INVALID": "Não consegui entender a consulta. Envie uma pergunta culinária em texto (3 a 500 "
    "caracteres) e, se quiser, até 30 ingredientes.",
    "OUT_OF_SCOPE": "Posso ajudar apenas com receitas e ingredientes da nossa base culinária.",
    "PROMPT_INJECTION": "Não posso atender a esse pedido. Posso ajudar com receitas e ingredientes da nossa base.",
}

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_INVISIBLE_RE = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")
_INGREDIENT_RE = re.compile(r"^[\w\s\-'’.,/()%ºª°]+$", re.UNICODE)
ALLOWED_KEYS = {"question", "available_ingredients"}


@dataclass(frozen=True)
class InputDecision:
    allowed: bool
    code: InputCode | None = None
    message: str = ""
    consultation: ConsultationInput | None = None
    signals: tuple[str, ...] = field(default_factory=tuple)  # para log; nunca contém o texto do usuário

    @classmethod
    def block(cls, code: InputCode, *signals: str) -> InputDecision:
        return cls(allowed=False, code=code, message=MESSAGES[code], signals=tuple(signals))


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE_RE.sub("", text)
    return " ".join(text.split())


def check_input(raw: Any, settings: Settings | None = None) -> InputDecision:
    s = settings or Settings()

    # 1. formato
    if not isinstance(raw, Mapping):
        return InputDecision.block("INPUT_INVALID", "not_object")
    extra = set(raw) - ALLOWED_KEYS
    if extra:
        return InputDecision.block("INPUT_INVALID", "unexpected_fields")
    question = raw.get("question")
    ingredients_raw = raw.get("available_ingredients")
    if not isinstance(question, str):
        return InputDecision.block("INPUT_INVALID", "question_type")
    if ingredients_raw is None:
        ingredients_raw = []
    if not isinstance(ingredients_raw, list) or not all(isinstance(i, str) for i in ingredients_raw):
        return InputDecision.block("INPUT_INVALID", "ingredients_type")
    if len(question) > s.max_question_chars * 4 or len(ingredients_raw) > s.max_ingredients * 4:
        return InputDecision.block("INPUT_INVALID", "payload_too_large")  # antes de normalizar

    # 2. limpeza e limites
    if _CONTROL_RE.search(question) or any(_CONTROL_RE.search(i) for i in ingredients_raw):
        return InputDecision.block("INPUT_INVALID", "control_chars")
    question = _clean(question)
    if not (s.min_question_chars <= len(question) <= s.max_question_chars):
        return InputDecision.block("INPUT_INVALID", "question_length")
    ingredients: list[str] = []
    seen: set[str] = set()
    for item in ingredients_raw:
        item = _clean(item)
        if not item:
            continue
        if len(item) > s.max_ingredient_chars or not _INGREDIENT_RE.match(item):
            return InputDecision.block("INPUT_INVALID", "ingredient_format")
        key = lexicon.fold(item)
        if key not in seen:
            seen.add(key)
            ingredients.append(item)
    if len(ingredients) > s.max_ingredients:
        return InputDecision.block("INPUT_INVALID", "too_many_ingredients")
    if lexicon.HTML_TAG_RE.search(question):
        return InputDecision.block("INPUT_INVALID", "html_markup")

    # 3. prompt injection (pergunta e ingredientes)
    combined = question + "\n" + "\n".join(ingredients)
    inj = lexicon.injection_signals(combined)
    if inj:
        return InputDecision.block("PROMPT_INJECTION", *inj)

    # 4. escopo
    culinary = lexicon.has_culinary_signal(combined) or bool(ingredients)
    if lexicon.strong_off_domain(question):
        return InputDecision.block("OUT_OF_SCOPE", "explicit_off_domain_request")
    if lexicon.weak_off_domain(question) and not culinary:
        return InputDecision.block("OUT_OF_SCOPE", "off_domain_topic")

    return InputDecision(
        allowed=True,
        consultation=ConsultationInput(question=question, available_ingredients=ingredients),
        signals=("culinary" if culinary else "neutral",),
    )
