"""Cliente HTTP do Ollama (API nativa /api/chat) com suporte a tool calling.

Formato (docs oficiais do Ollama, tool-calling):
  resposta  message.tool_calls = [{"type": "function", "function": {"index": 0, "name": ..., "arguments": {...}}}]
  resultado {"role": "tool", "tool_name": <nome>, "content": <texto>}
O cliente preserva `index` e, se a versão do servidor enviar, `id` (repassado como `tool_call_id`).

O conteúdo gerado pelo modelo NUNCA é evidência: só os resultados MCP do turno são (ver orchestrator).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.settings import Settings

logger = logging.getLogger("app.ollama_client")

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class LLMError(Exception):
    """code: LLM_UNAVAILABLE | LLM_PROTOCOL_ERROR | UPSTREAM_TIMEOUT"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Any
    index: int | None = None
    id: str | None = None


@dataclass(frozen=True)
class ChatResponse:
    content: str
    tool_calls: list[ToolCall]
    assistant_message: dict[str, Any]  # para anexar ao histórico (sem o "thinking")
    done_reason: str | None = None
    duration_ms: float = 0.0
    eval_count: int | None = None
    prompt_eval_count: int | None = None
    thinking: str | None = field(default=None, repr=False)


class OllamaClient:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._http = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(settings.ollama_timeout, connect=5.0),
            transport=transport,
        )
        self._send_think = settings.ollama_think is not None

    async def __aenter__(self) -> OllamaClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------ chamadas

    def _payload(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
                 fmt: dict[str, Any] | str | None) -> dict[str, Any]:
        s = self.settings
        payload: dict[str, Any] = {
            "model": s.ollama_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": s.ollama_temperature, "num_ctx": s.ollama_num_ctx,
                        "num_predict": s.ollama_num_predict},
        }
        if tools:
            payload["tools"] = tools
        if fmt is not None:
            payload["format"] = fmt
        if self._send_think:
            payload["think"] = s.ollama_think
        return payload

    async def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        try:
            return await self._http.post(path, json=payload)
        except httpx.TimeoutException:
            raise LLMError("UPSTREAM_TIMEOUT", "Tempo esgotado aguardando o modelo de linguagem.") from None
        except httpx.HTTPError as exc:
            logger.error("Ollama inacessível em %s: %r", self.settings.ollama_base_url, exc)
            raise LLMError("LLM_UNAVAILABLE", "Serviço de modelo de linguagem indisponível.") from None

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        format: dict[str, Any] | str | None = None,  # noqa: A002 - nome do campo da API
    ) -> ChatResponse:
        started = time.perf_counter()
        resp = await self._post("/api/chat", self._payload(messages, tools, format))
        if resp.status_code == 400 and self._send_think and "think" in resp.text.lower():
            # Modelo/versão sem suporte ao parâmetro `think`: repete uma vez sem ele.
            logger.warning("Ollama recusou o parâmetro think; repetindo sem ele")
            self._send_think = False
            resp = await self._post("/api/chat", self._payload(messages, tools, format))
        self._raise_for_status(resp)
        try:
            data = resp.json()
        except json.JSONDecodeError:
            raise LLMError("LLM_PROTOCOL_ERROR", "Resposta do modelo não é JSON.") from None
        return self._parse(data, (time.perf_counter() - started) * 1000)

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        body = resp.text[:300]
        if resp.status_code == 404 and "not found" in body.lower():
            logger.error("modelo %s não encontrado no Ollama (ollama pull %s)", self.settings.ollama_model,
                         self.settings.ollama_model)
            raise LLMError("LLM_UNAVAILABLE", "Modelo de linguagem não instalado.")
        if resp.status_code >= 500:
            logger.error("Ollama HTTP %s: %s", resp.status_code, body)
            raise LLMError("LLM_UNAVAILABLE", "Serviço de modelo de linguagem com falha.")
        logger.error("Ollama HTTP %s: %s", resp.status_code, body)
        raise LLMError("LLM_PROTOCOL_ERROR", "Requisição rejeitada pelo modelo de linguagem.")

    @staticmethod
    def _parse(data: Any, duration_ms: float) -> ChatResponse:
        msg = data.get("message") if isinstance(data, dict) else None
        if not isinstance(msg, dict):
            raise LLMError("LLM_PROTOCOL_ERROR", "Resposta do modelo sem campo message.")
        content = msg.get("content") or ""
        if not isinstance(content, str):
            raise LLMError("LLM_PROTOCOL_ERROR", "Conteúdo da resposta em formato inesperado.")
        thinking = msg.get("thinking") if isinstance(msg.get("thinking"), str) else None
        content = _THINK_RE.sub("", content).strip()

        raw_calls = msg.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            raise LLMError("LLM_PROTOCOL_ERROR", "tool_calls em formato inesperado.")
        calls: list[ToolCall] = []
        for i, raw in enumerate(raw_calls):
            fn = raw.get("function") if isinstance(raw, dict) else None
            if not isinstance(fn, dict) or not isinstance(fn.get("name"), str):
                raise LLMError("LLM_PROTOCOL_ERROR", "tool_call sem nome de função.")
            index = fn.get("index", i)
            calls.append(
                ToolCall(
                    name=fn["name"],
                    arguments=fn.get("arguments"),
                    index=index if isinstance(index, int) else i,
                    id=raw.get("id") if isinstance(raw.get("id"), str) else None,
                )
            )
        assistant: dict[str, Any] = {"role": "assistant", "content": content}
        if raw_calls:
            assistant["tool_calls"] = raw_calls
        return ChatResponse(
            content=content,
            tool_calls=calls,
            assistant_message=assistant,
            done_reason=data.get("done_reason"),
            duration_ms=duration_ms,
            eval_count=data.get("eval_count"),
            prompt_eval_count=data.get("prompt_eval_count"),
            thinking=thinking,
        )

    @staticmethod
    def tool_message(call: ToolCall, content: str) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "tool", "tool_name": call.name, "content": content}
        if call.id:
            msg["tool_call_id"] = call.id
        return msg

    # ------------------------------------------------------------ disponibilidade

    async def check(self) -> dict[str, Any]:
        """Para /ready e para o smoke test: servidor acessível, modelo instalado, suporte a tools."""
        out: dict[str, Any] = {"reachable": False, "model": self.settings.ollama_model, "model_present": False,
                               "supports_tools": None, "version": None}
        try:
            v = await self._http.get("/api/version")
            out["reachable"] = v.status_code == 200
            out["version"] = v.json().get("version") if v.status_code == 200 else None
            show = await self._http.post("/api/show", json={"model": self.settings.ollama_model})
        except (httpx.HTTPError, ValueError):
            return out
        if show.status_code == 200:
            out["model_present"] = True
            caps = show.json().get("capabilities")
            if isinstance(caps, list):
                out["supports_tools"] = "tools" in caps
        return out
