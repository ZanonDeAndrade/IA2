"""Contratos HTTP da consulta (docs/08-application/contracts.md e backend.md).

POST /api/v1/consultations
  entrada: {question, available_ingredients?}
  saída:   {request_id, status, answer, recipes, sources, error?}
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["FOUND", "INSUFFICIENT", "BLOCKED", "ERROR"]

ErrorCode = Literal[
    "INPUT_INVALID",
    "OUT_OF_SCOPE",
    "PROMPT_INJECTION",
    "CORPUS_EMPTY",
    "DOCUMENT_NOT_FOUND",
    "MCP_UNAVAILABLE",
    "MCP_TOOL_ERROR",
    "LLM_UNAVAILABLE",
    "LLM_PROTOCOL_ERROR",
    "UPSTREAM_TIMEOUT",
    "INTERNAL_ERROR",
]


class ConsultationInput(BaseModel):
    """Entrada já validada pelo guardrail de entrada (strict: sem coerção de tipos)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    question: str = Field(min_length=3, max_length=500)
    available_ingredients: list[str] = Field(default_factory=list, max_length=30)


class IngredientView(BaseModel):
    name: str
    quantity_text: str | None = None
    required: bool = True
    notes: str | None = None


class RecipeCard(BaseModel):
    """Montado pelo backend a partir dos objetos MCP; nenhum campo vem do texto livre do LLM."""

    recipe_id: str
    document_id: str
    title: str
    topic_key: str
    compatibility: Literal["COMPLETE", "PARTIAL", "NO_MATCH", "NOT_EVALUATED"]
    available_ingredients: list[str]
    missing_ingredients: list[str]
    ingredients: list[IngredientView]
    instructions: list[str]
    portions: str | None = None
    preparation_time: str | None = None
    temperature: str | None = None
    source_url: str
    source_id: str  # = document_id (nome usado no exemplo de backend.md)


class SourceRef(BaseModel):
    document_id: str
    recipe_id: str
    title: str
    url: str
    license: str | None = None


class ErrorInfo(BaseModel):
    code: ErrorCode
    message: str


class ConsultationOutput(BaseModel):
    request_id: str
    status: Status
    answer: str
    recipes: list[RecipeCard] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    error: ErrorInfo | None = None


# Mapeamento sugerido para a camada HTTP (prompt 27). INSUFFICIENT responde 200 (status semântico);
# bloqueios usam 422 como em architecture.md §5 e no diagrama de guardrails.
HTTP_STATUS_BY_CODE: dict[str, int] = {
    "INPUT_INVALID": 422,
    "OUT_OF_SCOPE": 422,
    "PROMPT_INJECTION": 422,
    "CORPUS_EMPTY": 503,
    "MCP_UNAVAILABLE": 503,
    "LLM_UNAVAILABLE": 503,
    "UPSTREAM_TIMEOUT": 504,
    "MCP_TOOL_ERROR": 502,
    "LLM_PROTOCOL_ERROR": 502,
    "DOCUMENT_NOT_FOUND": 200,
    "INTERNAL_ERROR": 500,
}


def http_status_for(output: ConsultationOutput) -> int:
    return HTTP_STATUS_BY_CODE.get(output.error.code, 500) if output.error else 200
