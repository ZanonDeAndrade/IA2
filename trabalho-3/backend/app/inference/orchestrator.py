"""Orquestração da inferência (prompts 21 a 23): intenção -> LLM <-> ferramentas MCP -> seleção programática.

Fluxo de um turno:
  0. o LLM classifica a intenção (saída estruturada) e o backend valida o plano (app/inference/intent.py)
  1. system prompt + plano + mensagem do usuário + SÓ as tools coerentes com a intenção
     (pedido de receitas: search_knowledge/get_document; pergunta sobre categorias: list_topics)
  2. loop: o LLM pede tool_calls -> validação (allowlist da intenção, duplicadas, limite) -> MCP tools/call
     -> resultado neutralizado e compactado volta como mensagem `tool`. Em search_knowledge o backend garante
     os ingredientes do usuário e o critério de ordenação (compatibilidade é calculada no servidor MCP).
  3. se o LLM não chamar a ferramenta exigida: UMA instrução; se ainda assim não chamar, o backend executa
     a chamada via MCP (nunca há resposta sem evidência)
  4. resposta final JSON {status, answer, recipe_ids}; o backend seleciona e ordena as receitas
     (app/inference/recommend.py): o LLM escolhe entre candidatos elegíveis, não decide compatibilidade
  5. receitas escolhidas são completadas com get_document via MCP; guardrail de saída na narrativa; se rejeitar:
     UMA reformulação; se rejeitar de novo ou se a seleção mudou: resposta-modelo determinística

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
from app.inference.intent import NAME_INTENTS, QueryPlan, classify
from app.inference.recommend import Selection, insufficient_answer, select, template_answer
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
    intent: str | None = None
    situation: str | None = None


def _category(item: dict[str, Any]) -> str | None:
    label, sub = item.get("topic_label"), item.get("subcategory")
    return f"{label} › {sub}" if label and sub else label or item.get("topic_key")


def compact_for_llm(name: str, data: Any) -> Any:
    """Visão enxuta do resultado MCP para o LLM (menos tokens = menos latência em CPU).

    A evidência completa continua no EvidenceSet: cards, guardrail e fontes usam o resultado integral.
    """
    if not isinstance(data, dict) or data.get("error"):
        return data
    if name == "search_knowledge":
        return {
            "evidence_status": data.get("evidence_status"),
            "ranking": data.get("ranking"),
            "results": [
                {"recipe_id": r.get("recipe_id"), "title": r.get("title"), "categoria": _category(r),
                 "compatibility": r.get("compatibility"),
                 "available_ingredients": r.get("available_ingredients"),
                 "missing_ingredients": r.get("missing_ingredients"),
                 "trecho": (r.get("source_excerpt") or "")[:220]}
                for r in data.get("results") or []
            ],
        }
    if name == "get_document" and data.get("found") and isinstance(data.get("recipe"), dict):
        rec = data["recipe"]
        return {"found": True, "recipe": {
            "recipe_id": rec.get("recipe_id"), "title": rec.get("title"), "categoria": _category(rec),
            "ingredients": [" ".join(x for x in (i.get("quantity_text"), i.get("name_original")) if x)
                            for i in rec.get("ingredients") or []],
            "instructions": [str(step)[:200] for step in (rec.get("instructions") or [])[:10]],
        }}
    if name == "list_topics":
        return {"topics": [{"topic_key": t.get("topic_key"), "label": t.get("label"),
                            "recipe_count": t.get("recipe_count")} for t in data.get("topics") or []],
                "total_recipes": data.get("total_recipes")}
    return data


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
        self.plan: QueryPlan | None = None
        self.messages: list[dict[str, Any]] = []

    # ------------------------------------------------------------ util

    def _t(self, step: str, **kw: Any) -> None:
        self.trace.append({"step": step, **{k: v for k, v in kw.items() if v is not None}})

    async def _chat(self, *, tools: bool, fmt: dict[str, Any] | None = None, label: str = "llm") -> ChatResponse:
        try:
            resp = await self.llm.chat(self.messages, tools=self._offered_tools() if tools else None, format=fmt)
        except LLMError as exc:
            self._t(label, ok=False, error_code=exc.code)
            raise InferenceError(exc.code, exc.message, self.trace) from None
        self._t(label, ok=True, duration_ms=round(resp.duration_ms), tool_calls=[c.name for c in resp.tool_calls],
                eval_count=resp.eval_count, done_reason=resp.done_reason)
        return resp

    # ------------------------------------------------------------ ferramentas

    def _offered_tools(self) -> list[dict[str, Any]]:
        names = self.plan.tools if self.plan else frozenset(self.allowed)
        return [t for t in self.mcp.llm_tools() if t["function"]["name"] in names]

    def _search_arguments(self, args: dict[str, Any]) -> dict[str, Any]:
        """Parâmetros da busca garantidos pelo sistema: ingredientes do usuário, ordenação e, para buscas por nome,
        o prato pedido. A consulta textual do LLM é mantida nas demais intenções."""
        assert self.plan is not None
        out = self.plan.search_arguments()
        query = args.get("query")
        if self.plan.intent not in NAME_INTENTS and isinstance(query, str) and len(query.strip()) >= 3:
            out["query"] = query.strip()[:500]
        if self.plan.intent == "recipes_by_category" and isinstance(args.get("topic_key"), str):
            out["topic_key"] = args["topic_key"]
        return out

    async def _execute(self, call: ToolCall) -> str:
        args = call.arguments
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                args = {"_raw": args}
        if call.name == "search_knowledge" and self.plan is not None:
            args = self._search_arguments(args if isinstance(args, dict) else {})
        key = f"{call.name}:{json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)}"
        arg_keys = sorted(args) if isinstance(args, dict) else None

        if call.name not in self.allowed:
            self._t("tool", tool=call.name[:64], ok=False, error_code="TOOL_NOT_ALLOWED")
            return json.dumps({"error": {"code": "TOOL_NOT_ALLOWED",
                                         "message": "Ferramenta inexistente. Use apenas as ferramentas anunciadas."}})
        if self.plan is not None and call.name not in self.plan.tools:
            self._t("tool", tool=call.name, ok=False, error_code="TOOL_NOT_FOR_INTENT")
            return json.dumps({"error": {"code": "TOOL_NOT_FOR_INTENT",
                                         "message": f"Ferramenta inadequada para este pedido. Use {self.plan.required_tool}."}},
                              ensure_ascii=False)
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
        content = json.dumps(compact_for_llm(call.name, safe), ensure_ascii=False)
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
        try:
            self.plan, info = await classify(self.llm, self.c)
        except LLMError as exc:
            self._t("intent", ok=False, error_code=exc.code)
            raise InferenceError(exc.code, exc.message, self.trace) from None
        self._t("intent", ok=True, **{k: v for k, v in info.items() if v is not None})
        self.messages = [
            {"role": "system", "content": sp.SYSTEM_PROMPT},
            {"role": "system", "content": self.plan.describe()},
            {"role": "user", "content": sp.user_message(self.c.question, list(self.plan.ingredients))},
        ]

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
            if self.plan.required_tool not in self.evidence.tool_names and not nudged and can_call:
                nudged = True  # respondeu sem consultar a ferramenta da intenção: UMA instrução
                self.messages.append(resp.assistant_message)
                self.messages.append({"role": "user", "content": sp.required_tool_instruction(self.plan.required_tool)})
                self._t("nudge", reason=f"missing_{self.plan.required_tool}")
                continue
            final_content = resp.content
            self.messages.append(resp.assistant_message)
            break
        else:
            self._t("limit", reason="max_llm_rounds")

        if self.plan.required_tool not in self.evidence.tool_names:
            await self._system_retrieval()
            final_content = None  # a resposta anterior não tinha evidência

        if self.plan.intent == "list_categories":
            return await self._categories_result(final_content)
        return await self._recipes_result(final_content)

    async def _system_retrieval(self) -> None:
        """O LLM não chamou a ferramenta exigida nem após a instrução: o backend a executa via MCP."""
        assert self.plan is not None
        tool = self.plan.required_tool
        args: dict[str, Any] = self.plan.search_arguments() if tool == "search_knowledge" else {"include_counts": True}
        content = await self._execute(ToolCall(name=tool, arguments=args))
        self._t("system_retrieval", tool=tool)
        self.messages.append({"role": "user", "content": sp.SYSTEM_SEARCH_NOTE.format(tool=tool, content=content)})

    async def _structured_final(self, instruction: str) -> LLMFinal | None:
        """Pede o JSON final sem tools e com `format` = schema (structured outputs do Ollama)."""
        self.messages.append({"role": "user", "content": instruction})
        resp = await self._chat(tools=False, fmt=sp.FINAL_ANSWER_SCHEMA, label="llm_final")
        self.messages.append(resp.assistant_message)
        return parse_final(resp.content)

    async def _verify(self, final: LLMFinal, *, topics_allowed: bool = False) -> OutputVerdict:
        verdict = check_output(final, self.evidence, self.c, self.s.max_recipes, topics_allowed=topics_allowed)
        self._t("guardrail", ok=verdict.ok, violations=list(verdict.violations) or None)
        return verdict

    # ------------------------------------------------------------ resultados

    async def _categories_result(self, final_content: str | None) -> InferenceResult:
        if not self.evidence.topics:
            return self._insufficient(("NO_TOPICS",), INSUFFICIENT_MESSAGE)
        final = parse_final(final_content or "") or await self._structured_final(sp.FINAL_JSON_INSTRUCTION)
        if final is not None and final.status == "FOUND":
            verdict = await self._verify(LLMFinal("FOUND", final.answer, ()), topics_allowed=True)
            if verdict.ok:
                return self._found(verdict.answer, (), "llm", None)
        self._t("final", origin="template")
        return self._found(topics_answer(self.evidence), (), "template", None)

    async def _recipes_result(self, final_content: str | None) -> InferenceResult:
        assert self.plan is not None
        final = parse_final(final_content or "")
        if final is None and self.evidence.hits:
            final = await self._structured_final(sp.FINAL_JSON_INSTRUCTION)
        llm_ids = tuple(final.recipe_ids) if final is not None and final.status == "FOUND" else ()
        selection = select(self.plan, self.evidence, llm_ids, self.s.max_recipes)
        self._t("selection", candidates=selection.candidates, chosen=list(selection.recipe_ids),
                situation=selection.situation, changed=selection.changed)
        if not selection.recipe_ids:
            return self._insufficient(("NO_ELIGIBLE_RECIPE",), insufficient_answer(self.plan))

        await self._enrich(selection.recipe_ids)
        violations: tuple[str, ...] = tuple(f"UNKNOWN_RECIPE_ID:{r[:60]}" for r in llm_ids
                                            if r not in self.evidence.recipe_ids)
        if final is not None and final.status == "FOUND" and not selection.changed:
            verdict = await self._verify(LLMFinal("FOUND", final.answer, selection.recipe_ids))
            if verdict.ok:
                return self._found(verdict.answer, selection.recipe_ids, "llm", selection)
            violations += verdict.violations
            retry = await self._structured_final(sp.rewrite_instruction(list(verdict.violations)))
            if retry is not None and retry.status == "FOUND":
                verdict2 = await self._verify(LLMFinal("FOUND", retry.answer, selection.recipe_ids))
                if verdict2.ok:
                    return self._found(verdict2.answer, selection.recipe_ids, "llm_rewrite", selection, violations)
                violations += verdict2.violations
        elif final is not None and final.status == "FOUND":
            violations += ("SELECTION_ADJUSTED",)
        self._t("final", origin="template")
        return self._found(template_answer(self.plan, self.evidence, selection), selection.recipe_ids, "template",
                           selection, violations)

    def _found(self, answer: str, ids: tuple[str, ...], origin: AnswerOrigin, selection: Selection | None,
               violations: tuple[str, ...] = ()) -> InferenceResult:
        return InferenceResult("FOUND", answer, ids, self.evidence, origin, violations, self.trace,
                               self.plan.intent if self.plan else None, selection.situation if selection else None)

    def _insufficient(self, violations: tuple[str, ...], message: str = "") -> InferenceResult:
        self._t("final", origin="canonical_insufficient")
        return InferenceResult("INSUFFICIENT", message or INSUFFICIENT_MESSAGE, (), self.evidence,
                               "canonical_insufficient", violations, self.trace,
                               self.plan.intent if self.plan else None, "NONE")


def topics_answer(evidence: EvidenceSet) -> str:
    parts = [f"{t['label']} ({t['recipe_count']})" if t.get("recipe_count") is not None else str(t["label"])
             for t in evidence.topics]
    return "Categorias disponíveis na base: " + ", ".join(parts) + "."
