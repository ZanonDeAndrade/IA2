"""Aplicação FastAPI (prompt 27).

    cd backend && .venv/bin/uvicorn app.main:app --port 8000

O lifespan abre UMA sessão MCP (subprocesso stdio) e UM cliente Ollama para o processo inteiro e os fecha
no encerramento. Se o MCP não subir, a API continua no ar: /health responde, /ready aponta MCP_UNAVAILABLE
e as consultas retornam 503 MCP_UNAVAILABLE pelo próprio QueryService.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.integrations.mcp_client import MCPClient, MCPClientError
from app.integrations.ollama_client import OllamaClient
from app.schemas.query import ConsultationOutput, ErrorInfo
from app.services.query_service import ERROR_MESSAGES, QueryService
from app.settings import Settings

logger = logging.getLogger("app.main")


def create_app(
    *,
    settings: Settings | None = None,
    mcp: MCPClient | None = None,
    llm: OllamaClient | None = None,
) -> FastAPI:
    """`mcp` e `llm` podem ser injetados (testes); por padrão vêm do ambiente. O MCP é iniciado aqui."""
    s = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = mcp or MCPClient.from_env()
        model = llm or OllamaClient(s)
        try:
            await client.start()
        except MCPClientError as exc:
            logger.error("MCP indisponível na inicialização (%s); consultas responderão 503", exc.code)
        app.state.settings = s
        app.state.mcp = client
        app.state.llm = model
        app.state.service = QueryService(client, model, s)
        try:
            yield
        finally:
            await client.close()
            await model.aclose()

    app = FastAPI(title="Assistente Inteligente de Receitas", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(s.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Request-ID"],
    )
    app.include_router(router)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:  # nunca expõe stack trace
        rid = uuid.uuid4().hex[:16]
        logger.error("request_id=%s erro não tratado: %s", rid, type(exc).__name__)
        msg = ERROR_MESSAGES["INTERNAL_ERROR"]
        out = ConsultationOutput(request_id=rid, status="ERROR", answer=msg,
                                 error=ErrorInfo(code="INTERNAL_ERROR", message=msg))
        return JSONResponse(out.model_dump(mode="json"), status_code=500, headers={"X-Request-ID": rid})

    return app


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = create_app()
