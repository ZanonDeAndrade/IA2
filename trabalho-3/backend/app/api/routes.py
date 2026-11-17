"""Rotas HTTP (prompt 27). Só transportam e normalizam: toda a regra está em QueryService.

POST /api/v1/consultations  consulta culinária (contrato em app/schemas/query.py)
GET  /health                processo vivo; não toca MCP nem LLM
GET  /ready                 MCP conectado, corpus preparado e modelo disponível (sem URLs nem detalhes internos)
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.integrations.mcp_client import MCPClient, MCPClientError
from app.integrations.ollama_client import OllamaClient
from app.schemas.query import ConsultationInput, ConsultationOutput, http_status_for
from app.services.query_service import QueryService
from app.settings import Settings

logger = logging.getLogger("app.api")

router = APIRouter()

READY_TIMEOUT = 10.0  # segundos por verificação em /ready

_INVALID_BODY = object()  # corpo ausente, grande demais ou JSON inválido: o guardrail responde INPUT_INVALID


async def _read_json(request: Request, limit: int) -> Any:
    """Lê o corpo com teto de tamanho (sem carregar corpos enormes) e decodifica JSON."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return _INVALID_BODY
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks))
    except (ValueError, UnicodeDecodeError):
        return _INVALID_BODY


@router.post(
    "/api/v1/consultations",
    response_model=ConsultationOutput,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": ConsultationInput.model_json_schema()}},
        }
    },
)
async def create_consultation(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    service: QueryService = request.app.state.service
    rid = uuid.uuid4().hex[:16]
    raw = await _read_json(request, settings.max_body_bytes)
    out = await service.consult(None if raw is _INVALID_BODY else raw, request_id=rid)
    status_code = http_status_for(out)
    logger.info("POST /api/v1/consultations request_id=%s status=%s http=%d", rid, out.status, status_code)
    return JSONResponse(out.model_dump(mode="json"), status_code=status_code, headers={"X-Request-ID": rid})


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    mcp: MCPClient = request.app.state.mcp
    llm: OllamaClient = request.app.state.llm
    problems: list[str] = []

    mcp_connected = False
    corpus_ready: bool | None = None
    with anyio.move_on_after(READY_TIMEOUT):
        mcp_connected = await mcp.ping()
        if mcp_connected:
            try:
                topics = await mcp.call_tool("list_topics", {"include_counts": False})
                corpus_ready = bool(topics.data.get("corpus_ready"))
            except MCPClientError as exc:
                problems.append(exc.code)
    if not mcp_connected:
        problems.append("MCP_UNAVAILABLE")
    elif corpus_ready is False:
        problems.append("CORPUS_EMPTY")

    llm_info: dict[str, Any] = {"reachable": False, "model": llm.settings.ollama_model, "model_present": False,
                                "supports_tools": None}
    with anyio.move_on_after(READY_TIMEOUT):
        checked = await llm.check()
        llm_info = {k: checked.get(k) for k in llm_info}
    if not llm_info["reachable"]:
        problems.append("LLM_UNAVAILABLE")
    elif not llm_info["model_present"]:
        problems.append("LLM_MODEL_MISSING")
    elif llm_info["supports_tools"] is False:
        problems.append("LLM_NO_TOOL_SUPPORT")

    body = {
        "ready": not problems,
        "checks": {"mcp": {"connected": mcp_connected, "corpus_ready": corpus_ready}, "llm": llm_info},
        "problems": problems,
    }
    return JSONResponse(body, status_code=200 if not problems else 503)
