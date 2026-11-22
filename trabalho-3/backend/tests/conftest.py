import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

FIXTURES = BACKEND / "tests" / "fixtures"
MCP_FIXTURES = ROOT / "mcp-server" / "tests" / "fixtures"  # fixture_retriever.py (substituto do RAG)


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------- LLM roteirizado (FIXTURE)


def tool_call(name: str, arguments: Any, index: int = 0) -> dict:
    return {"type": "function", "function": {"index": index, "name": name, "arguments": arguments}}


def llm_tools(*calls: dict, content: str = "") -> dict:
    return {"model": "fixture", "done": True, "done_reason": "stop",
            "message": {"role": "assistant", "content": content, "tool_calls": list(calls)}}


def llm_text(content: str) -> dict:
    return {"model": "fixture", "done": True, "done_reason": "stop", "eval_count": 10,
            "message": {"role": "assistant", "content": content}}


def llm_intent(intencao: str = "receitas_por_ingredientes", prato: str = "", ingredientes: list[str] | None = None,
               consulta: str = "") -> dict:
    """Resposta do passo de classificação de intenção (saída estruturada do LLM)."""
    return llm_text(json.dumps({"intencao": intencao, "prato": prato, "ingredientes": ingredientes or [],
                                "consulta": consulta}, ensure_ascii=False))


def is_intent_request(payload: dict) -> bool:
    fmt = payload.get("format")
    return isinstance(fmt, dict) and "intencao" in (fmt.get("properties") or {})


def llm_final(status: str, answer: str, recipe_ids: list[str] | None = None) -> dict:
    return llm_text(json.dumps({"status": status, "answer": answer, "recipe_ids": recipe_ids or []},
                               ensure_ascii=False))


class ScriptedOllama:
    """Servidor Ollama FALSO no nível de transporte HTTP: o OllamaClient real é exercitado.

    Cada item do roteiro é um dict de resposta, ou uma função (payload_da_requisição) -> dict.
    Requisições recebidas ficam em `requests` para inspeção (ex.: provar que o resultado MCP
    voltou ao modelo como mensagem `tool`).
    """

    def __init__(self, *script: dict | Callable[[dict], dict], status: int = 200, intent: dict | None = None) -> None:
        self.script = list(script)
        self.requests: list[dict] = []
        self.intent_requests: list[dict] = []
        self.status = status
        self.intent = intent  # resposta do classificador de intenção (obrigatória quando o fluxo chega ao LLM)

    def handler(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else {}
        if request.url.path == "/api/chat" and is_intent_request(payload):
            self.intent_requests.append(payload)
            if self.intent is None:
                raise AssertionError("roteiro sem resposta de intenção: use ScriptedOllama(..., intent=llm_intent(...))")
            return httpx.Response(self.status, json=self.intent)
        self.requests.append({"path": request.url.path, **payload})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "fixture"})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "tools"]})
        if not self.script:
            return httpx.Response(200, json=llm_final("INSUFFICIENT", "roteiro esgotado"))
        step = self.script.pop(0)
        body = step(payload) if callable(step) else step
        return httpx.Response(self.status, json=body)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    @property
    def chat_requests(self) -> list[dict]:
        return [r for r in self.requests if r["path"] == "/api/chat"]


# ---------------------------------------------------------------- MCP real (subprocesso stdio)


@pytest.fixture
def mcp_fixture_env(monkeypatch):
    monkeypatch.setenv("RECIPES_JSON", str(FIXTURES / "recipes.json"))
    monkeypatch.setenv("RAG_RETRIEVER", "fixture_retriever:retrieve")
    monkeypatch.setenv("PYTHONPATH", str(MCP_FIXTURES))
    monkeypatch.setenv("MCP_LOG_LEVEL", "WARNING")
    monkeypatch.delenv("MCP_COMMAND", raising=False)
    monkeypatch.delenv("MCP_SCRIPT", raising=False)


@pytest.fixture
async def mcp(mcp_fixture_env):
    from app.integrations.mcp_client import MCPClient

    async with MCPClient.from_env(project_root=ROOT) as client:
        yield client
