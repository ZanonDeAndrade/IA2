"""Orquestração da inferência (prompts 21 a 23): LLM <-> ferramentas MCP, com limites.

Fluxo de um turno:
  1. system prompt + mensagem do usuário + tools descobertas via MCP (tools/list)
  2. loop: o LLM pede tool_calls -> validação (allowlist, duplicadas, limite) -> MCP tools/call
     -> resultado (neutralizado contra instruções embutidas) volta como mensagem `tool`
  3. resposta final JSON {status, answer, recipe_ids}; se não vier, um pedido estruturado (format=schema)
  4. receitas escolhidas sem get_document são completadas pelo backend via MCP (objeto canônico)
  5. guardrail de saída; se rejeitar: UMA reformulação; se rejeitar de novo: resposta-modelo
     determinística a partir do evidence_set, ou INSUFFICIENT

Nunca há loop infinito: max_llm_rounds, max_tool_calls e um prazo total (no query_service).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from app.guardrails import lexicon
from app.guardrails.output_guardrail import LLMFinal, OutputVerdict, check_output, parse_final
from app.inference import system_prompt as sp
from app.inference.evidence import EvidenceSet
from app.integrations.mcp_client import MCPClient, MCPClientError
from app.integrations.ollama_client import ChatResponse, LLMError, OllamaClient, ToolCall
from app.schemas.query import ConsultationInput
from app.settings import Settings

logger = logging.getLogger("app.orchestrator")

AnswerOrigin = Literal["llm", "llm_rewrite", "template", "canonical_insufficient"]

INSUFFICIENT_MESSAGE = (
    "Não encontrei na base documental receitas que sustentem uma resposta para essa consulta. "
    "Tente informar outros ingredientes ou reformular a pergunta."
)
NEUTRALIZED = "[trecho removido pelo sistema: continha instruções embutidas no documento]"
FATAL_MCP_CODES = {"MCP_UNAVAILABLE", "UPSTREAM_TIMEOUT"}


class InferenceError(Exception):
    """code: LLM_UNAVAILABLE | LLM_PROTOCOL_ERROR | UPSTREAM_TIMEOUT | MCP_UNAVAILABLE | CORPUS_EMPTY"""

    def __init__(self, code: str, message: str, trace: list[dict[str, Any]] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.trace = trace or []


@dataclass
class InferenceResult:
    status: Literal["FOUND", "INSUFFICIENT"]
    answer: str
    recipe_ids: tuple[str, ...]
    evidence: EvidenceSet
    origin: AnswerOrigin
    violations: tuple[str, ...] = ()
    trace: list[dict[str, Any]] = field(default_factory=list)


def neutralize(obj: Any, counter: list[int]) -> Any:
    """Cópia dos dados da tool com strings que contêm padrões de injeção substituídas."""
    if isinstance(obj, str):
        if lexicon.injection_signals(obj):
            counter[0] += 1
            return NEUTRALIZED
        return obj
    if isinstance(obj, dict):
        return {k: neutralize(v, counter) for k, v in obj.items()}
    if isinstance(obj, list):
        return [neutralize(v, counter) for v in obj]
    return obj


class Orchestrator:
    def __init__(self, llm: OllamaClient, mcp: MCPClient, settings: Settings) -> None:
        self.llm = llm
        self.mcp = mcp
        self.settings = settings

    async def run(self, consultation: ConsultationInput, request_id: str) -> InferenceResult:
        turn = _Turn(self, consultation, request_id)
        return await turn.run()


class _Turn:
    """Estado de UMA consulta (não compartilhado entre requisições)."""

    def __init__(self, orch: Orchestrator, consultation: ConsultationInput, request_id: str) -> None:
        self.llm, self.mcp, self.s = orch.llm, orch.mcp, orch.settings
        self.c = consultation
        self.rid = request_id
        self.evidence = EvidenceSet()
        self.trace: list[dict[str, Any]] = []
        self.tool_calls = 0
        self.seen: dict[str, str] = {}
        self.allowed = {t["function"]["name"] for t in self.mcp.llm_tools()}
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": sp.SYSTEM_PROMPT},
            {"role": "user", "content": sp.user_message(self.c.question, self.c.available_ingredients)},
        ]

    # ------------------------------------------------------------ util

    def _t(self, step: str, **kw: Any) -> None:
        self.trace.append({"step": step, **{k: v for k, v in kw.items() if v is not None}})

    async def _chat(self, *, tools: bool, fmt: dict[str, Any] | None = None, label: str = "llm") -> ChatResponse:
        try:
            resp = await self.llm.chat(self.messages, tools=self.mcp.llm_tools() if tools else None, format=fmt)
        except LLMError as exc:
            self._t(label, ok=False, error_code=exc.code)
            raise InferenceError(exc.code, exc.message, self.trace) from None
        self._t(label, ok=True, duration_ms=round(resp.duration_ms), tool_calls=[c.name for c in resp.tool_calls],
                eval_count=resp.eval_count, done_reason=resp.done_reason)
        return resp

    # ------------------------------------------------------------ ferramentas

    async def _execute(self, call: ToolCall) -> str:
        args = call.arguments
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                args = {"_raw": args}
        key = f"{call.name}:{json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)}"
        arg_keys = sorted(args) if isinstance(args, dict) else None

        if call.name not in self.allowed:
            self._t("tool", tool=call.name[:64], ok=False, error_code="TOOL_NOT_ALLOWED")
            return json.dumps({"error": {"code": "TOOL_NOT_ALLOWED",
                                         "message": "Ferramenta inexistente. Use apenas as ferramentas anunciadas."}})
        if key in self.seen:
            self._t("tool", tool=call.name, ok=True, duplicate=True)
            return self.seen[key]
        if self.tool_calls >= self.s.max_tool_calls:
            self._t("tool", tool=call.name, ok=False, error_code="TOOL_LIMIT_REACHED")
            return json.dumps({"error": {"code": "TOOL_LIMIT_REACHED",
                                         "message": "Limite de chamadas atingido. Responda com o que já foi obtido."}})
        self.tool_calls += 1
        try:
            result = await self.mcp.call_tool(call.name, args, request_id=self.rid)
        except MCPClientError as exc:
            self._t("tool", tool=call.name, ok=False, error_code=exc.code, detail_code=exc.detail_code, args=arg_keys)
            if exc.code in FATAL_MCP_CODES:
                raise InferenceError(exc.code, exc.message, self.trace) from None
            content = json.dumps({"error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False)
            self.seen[key] = content
            return content

        self.evidence.add(result)
        if result.error_code == "CORPUS_EMPTY":
            self._t("tool", tool=call.name, ok=True, business_error="CORPUS_EMPTY")
            raise InferenceError("CORPUS_EMPTY", "A base de receitas ainda não foi preparada.", self.trace)
        counter = [0]
        safe = neutralize(result.data, counter)
        self._t("tool", tool=call.name, ok=True, args=arg_keys, duration_ms=round(result.duration_ms),
                business_error=result.error_code, ids=[e["recipe_id"] for e in result.evidence] or None,
                neutralized=counter[0] or None)
        content = json.dumps(safe, ensure_ascii=False)
        self.seen[key] = content
        return content

    async def _enrich(self, recipe_ids: tuple[str, ...]) -> None:
        """Busca via MCP o objeto canônico das receitas escolhidas que ainda não têm get_document."""
        for rid in recipe_ids[: self.s.max_recipes]:
            if rid in self.evidence.documents or rid not in self.evidence.recipe_ids:
                continue
            try:
                result = await self.mcp.call_tool("get_document", {"recipe_id": rid}, request_id=self.rid)
            except MCPClientError as exc:
                self._t("enrich", recipe_id=rid, ok=False, error_code=exc.code)
                if exc.code in FATAL_MCP_CODES:
                    raise InferenceError(exc.code, exc.message, self.trace) from None
                continue
            self.evidence.add(result)
            self._t("enrich", recipe_id=rid, ok=bool(result.data.get("found")))

    # ------------------------------------------------------------ turno

    async def run(self) -> InferenceResult:
        final_content: str | None = None
        nudged = False
        for _ in range(self.s.max_llm_rounds):
            can_call = self.tool_calls < self.s.max_tool_calls
            resp = await self._chat(tools=can_call)
            if resp.tool_calls and can_call:
                self.messages.append(resp.assistant_message)
                for call in resp.tool_calls:
                    self.messages.append(OllamaClient.tool_message(call, await self._execute(call)))
                continue
            if not self.evidence.results and not nudged:
                # Respondeu sem consultar a base: uma única instrução de recuperação.
                nudged = True
                self.messages.append(resp.assistant_message)
                self.messages.append({"role": "user", "content": sp.RETRY_TOOL_INSTRUCTION})
                self._t("nudge", reason="no_tool_called")
                continue
            final_content = resp.content
            self.messages.append(resp.assistant_message)
            break
        else:
            self._t("limit", reason="max_llm_rounds")

        if not self.evidence.results:
            # O modelo não consultou nenhuma ferramenta: nada sustenta uma resposta.
            return self._insufficient(("NO_TOOL_EVIDENCE",))

        final = parse_final(final_content or "")
        if final is None:
            final = await self._structured_final(sp.FINAL_JSON_INSTRUCTION)
        if final is None:
            self._t("final", ok=False, reason="unparseable")
            return self._fallback(None, ("UNPARSEABLE_FINAL",))

        verdict = await self._verify(final)
        if verdict.ok:
            return self._result(verdict, "llm")

        retry = await self._structured_final(sp.rewrite_instruction(list(verdict.violations)))
        if retry is not None:
            verdict2 = await self._verify(retry)
            if verdict2.ok:
                return self._result(verdict2, "llm_rewrite", verdict.violations)
            return self._fallback(verdict2, verdict.violations + verdict2.violations)
        return self._fallback(verdict, verdict.violations)

    async def _structured_final(self, instruction: str) -> LLMFinal | None:
        """Pede o JSON final sem tools e com `format` = schema (structured outputs do Ollama)."""
        self.messages.append({"role": "user", "content": instruction})
        resp = await self._chat(tools=False, fmt=sp.FINAL_ANSWER_SCHEMA, label="llm_final")
        self.messages.append(resp.assistant_message)
        return parse_final(resp.content)

    async def _verify(self, final: LLMFinal) -> OutputVerdict:
        if final.status == "FOUND":
            await self._enrich(tuple(r for r in final.recipe_ids if r in self.evidence.recipe_ids))
        verdict = check_output(final, self.evidence, self.c, self.s.max_recipes)
        self._t("guardrail", ok=verdict.ok, violations=list(verdict.violations) or None)
        return verdict

    # ------------------------------------------------------------ resultados

    def _result(self, verdict: OutputVerdict, origin: AnswerOrigin,
                previous: tuple[str, ...] = ()) -> InferenceResult:
        if verdict.status == "INSUFFICIENT":
            return InferenceResult("INSUFFICIENT", verdict.answer, (), self.evidence, origin, previous, self.trace)
        return InferenceResult("FOUND", verdict.answer, verdict.recipe_ids, self.evidence, origin,
                               previous, self.trace)

    def _insufficient(self, violations: tuple[str, ...]) -> InferenceResult:
        self._t("final", origin="canonical_insufficient")
        return InferenceResult("INSUFFICIENT", INSUFFICIENT_MESSAGE, (), self.evidence, "canonical_insufficient",
                               violations, self.trace)

    def _fallback(self, verdict: OutputVerdict | None, violations: tuple[str, ...]) -> InferenceResult:
        """Resposta determinística montada só com o evidence_set (nenhum texto do LLM)."""
        ids: tuple[str, ...] = ()
        if verdict is not None and verdict.status == "FOUND":
            ids = verdict.recipe_ids
        if ids:
            self._t("final", origin="template")
            return InferenceResult("FOUND", template_answer(self.evidence, ids), ids, self.evidence, "template",
                                   violations, self.trace)
        if verdict is not None and verdict.status == "FOUND" and self.evidence.topics:
            self._t("final", origin="template")
            return InferenceResult("FOUND", topics_answer(self.evidence), (), self.evidence, "template",
                                   violations, self.trace)
        return self._insufficient(violations)


_COMPAT_TEXT = {
    "COMPLETE": "você informou todos os ingredientes obrigatórios (presença não garante quantidade suficiente)",
    "NOT_EVALUATED": "confira a lista de ingredientes na fonte",
    "NO_MATCH": "nenhum dos ingredientes obrigatórios coincide com os informados",
}


def template_answer(evidence: EvidenceSet, recipe_ids: tuple[str, ...]) -> str:
    lines = [f"Encontrei {len(recipe_ids)} receita(s) na base documental:"]
    for rid in recipe_ids:
        src = evidence.recipe_source(rid) or {}
        hit = evidence.hits.get(rid)
        compat = hit.compatibility if hit else "NOT_EVALUATED"
        if compat == "PARTIAL" and hit:
            text = "faltam " + ", ".join(hit.missing_ingredients)
        else:
            text = _COMPAT_TEXT.get(compat, _COMPAT_TEXT["NOT_EVALUATED"])
        lines.append(f"- {src.get('title', rid)}: {text}.")
    lines.append("Os ingredientes e o modo de preparo abaixo são reproduzidos da fonte indicada.")
    return "\n".join(lines)


def topics_answer(evidence: EvidenceSet) -> str:
    parts = [f"{t['label']} ({t['recipe_count']})" if t.get("recipe_count") is not None else str(t["label"])
             for t in evidence.topics]
    return "Categorias disponíveis na base: " + ", ".join(parts) + "."
