"""Fluxo completo de uma consulta (prompt 22):
user -> guardrail de entrada -> LLM <-> MCP (RAG) -> guardrail de saída -> ConsultationOutput.

A camada HTTP (prompt 27) só precisa chamar `await service.consult(body)` e usar
`schemas.query.http_status_for(output)`. Nenhum stack trace ou texto interno sai daqui.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict
from typing import Any

import anyio

from app.guardrails.input_guardrail import check_input
from app.inference.evidence import EvidenceSet
from app.inference.orchestrator import InferenceError, InferenceResult, Orchestrator
from app.integrations.mcp_client import MCPClient
from app.integrations.ollama_client import OllamaClient
from app.schemas.query import ConsultationOutput, ErrorInfo, IngredientView, RecipeCard, SourceRef
from app.settings import Settings

logger = logging.getLogger("app.query_service")

ERROR_MESSAGES = {
    "MCP_UNAVAILABLE": "O serviço de busca de receitas está indisponível no momento.",
    "MCP_TOOL_ERROR": "Não foi possível consultar a base de receitas agora.",
    "LLM_UNAVAILABLE": "O modelo de linguagem está indisponível no momento.",
    "LLM_PROTOCOL_ERROR": "O modelo de linguagem respondeu em formato inesperado.",
    "UPSTREAM_TIMEOUT": "A consulta demorou mais que o esperado. Tente novamente.",
    "CORPUS_EMPTY": "A base de receitas ainda não foi preparada.",
    "INTERNAL_ERROR": "Erro interno ao processar a consulta.",
}


def build_cards(evidence: EvidenceSet, recipe_ids: tuple[str, ...]) -> tuple[list[RecipeCard], list[SourceRef]]:
    """Cards e fontes SOMENTE a partir dos objetos MCP do turno (nunca do texto do LLM)."""
    cards: list[RecipeCard] = []
    sources: list[SourceRef] = []
    for rid in recipe_ids:
        doc = evidence.documents.get(rid)
        hit = evidence.hits.get(rid)
        src = evidence.recipe_source(rid)
        if src is None:
            continue
        opt = (doc or {}).get("optional_fields") or {}
        cards.append(
            RecipeCard(
                recipe_id=rid,
                document_id=src["document_id"],
                title=src["title"],
                topic_key=src["topic_key"],
                compatibility=hit.compatibility if hit else "NOT_EVALUATED",  # type: ignore[arg-type]
                available_ingredients=list(hit.available_ingredients) if hit else [],
                missing_ingredients=list(hit.missing_ingredients) if hit else [],
                ingredients=[
                    IngredientView(name=i["name_original"], quantity_text=i.get("quantity_text"),
                                   required=bool(i.get("required", True)), notes=i.get("notes"))
                    for i in (doc or {}).get("ingredients") or []
                ],
                instructions=list((doc or {}).get("instructions") or []),
                portions=opt.get("portions"),
                preparation_time=opt.get("preparation_time"),
                temperature=opt.get("temperature"),
                source_url=src["source_url"],
                source_id=src["document_id"],
            )
        )
        sources.append(SourceRef(document_id=src["document_id"], recipe_id=rid, title=src["title"],
                                 url=src["source_url"], license=(doc or {}).get("license")))
    return cards, sources


class QueryService:
    def __init__(self, mcp: MCPClient, llm: OllamaClient, settings: Settings, *, keep_traces: int = 50) -> None:
        self.mcp = mcp
        self.settings = settings
        self.orchestrator = Orchestrator(llm, mcp, settings)
        self.traces: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._keep = keep_traces

    def _remember(self, rid: str, trace: dict[str, Any]) -> None:
        self.traces[rid] = trace
        while len(self.traces) > self._keep:
            self.traces.popitem(last=False)

    def _error(self, rid: str, code: str, started: float, trace: list[dict[str, Any]] | None = None) -> ConsultationOutput:
        msg = ERROR_MESSAGES.get(code, ERROR_MESSAGES["INTERNAL_ERROR"])
        self._remember(rid, {"status": "ERROR", "error_code": code, "steps": trace or [],
                             "duration_ms": round((time.perf_counter() - started) * 1000)})
        logger.warning("request_id=%s status=ERROR code=%s", rid, code)
        return ConsultationOutput(request_id=rid, status="ERROR", answer=msg,
                                  error=ErrorInfo(code=code, message=msg))  # type: ignore[arg-type]

    async def consult(self, raw: Any, request_id: str | None = None) -> ConsultationOutput:
        rid = request_id or uuid.uuid4().hex[:16]
        started = time.perf_counter()

        decision = check_input(raw, self.settings)
        if not decision.allowed:
            assert decision.code is not None
            self._remember(rid, {"status": "BLOCKED", "error_code": decision.code, "signals": list(decision.signals),
                                 "steps": []})
            logger.info("request_id=%s status=BLOCKED code=%s signals=%s", rid, decision.code, decision.signals)
            return ConsultationOutput(request_id=rid, status="BLOCKED", answer=decision.message,
                                      error=ErrorInfo(code=decision.code, message=decision.message))
        assert decision.consultation is not None

        if not self.mcp.connected:
            return self._error(rid, "MCP_UNAVAILABLE", started)
        try:
            with anyio.fail_after(self.settings.inference_timeout):
                result: InferenceResult = await self.orchestrator.run(decision.consultation, rid)
        except TimeoutError:
            return self._error(rid, "UPSTREAM_TIMEOUT", started)
        except InferenceError as exc:
            return self._error(rid, exc.code, started, exc.trace)
        except Exception:
            logger.exception("request_id=%s falha inesperada na inferência", rid)
            return self._error(rid, "INTERNAL_ERROR", started)

        cards, sources = build_cards(result.evidence, result.recipe_ids)
        status = result.status
        if status == "FOUND" and not cards and not result.evidence.topics:
            status = "INSUFFICIENT"  # resposta sem fonte vira INSUFFICIENT
        answer = result.answer
        if status == "INSUFFICIENT":
            cards, sources = [], []
        duration = round((time.perf_counter() - started) * 1000)
        self._remember(rid, {"status": status, "origin": result.origin, "violations": list(result.violations),
                             "steps": result.trace, "duration_ms": duration,
                             "mcp_calls": [e for e in self.mcp.trace_for(rid) if e.get("event") == "call_tool"]})
        logger.info("request_id=%s status=%s origin=%s recipes=%s violations=%d ms=%d", rid, status, result.origin,
                    [c.recipe_id for c in cards], len(result.violations), duration)
        return ConsultationOutput(request_id=rid, status=status, answer=answer, recipes=cards, sources=sources)
