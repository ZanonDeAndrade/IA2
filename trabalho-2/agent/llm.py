"""Configuração comum dos clientes do agente e da avaliação."""

import os
from math import isfinite


def timeout_llm() -> float:
    segundos = float(os.getenv("LLM_TIMEOUT") or 25)
    if not isfinite(segundos) or segundos <= 0:
        raise ValueError("LLM_TIMEOUT deve ser positivo e finito.")
    return segundos


def opcoes_llm() -> dict:
    opcoes = {}
    if raciocinio := os.getenv("LLM_RACIOCINIO"):
        opcoes["reasoning_effort"] = raciocinio
    if limite := os.getenv("LLM_MAX_TOKENS"):
        opcoes["max_tokens"] = int(limite)
        if opcoes["max_tokens"] < 1:
            raise ValueError("LLM_MAX_TOKENS deve ser positivo.")
    return opcoes


def formato_json(campos: tuple[str, ...], escolhas: dict[str, list[str]] | None = None,
                 *, nulos: tuple[str, ...] = ()) -> dict:
    if os.getenv("LLM_JSON_MODE") != "1":
        return {}
    return {"response_format": {"type": "json_schema", "json_schema": {
        "name": "resposta_lance_a_lance", "strict": True,
        "schema": {"type": "object", "properties": {
            campo: {"type": ["string", "null"] if campo in nulos else "string",
                    **({"enum": escolhas[campo]} if escolhas and campo in escolhas else {})}
            for campo in campos
        },
                   "required": list(campos), "additionalProperties": False},
    }}}


def configurar_modelo(temperatura: float, timeout: float | None = None):
    provedor = (os.getenv("LLM_PROVIDER") or "openai").lower()
    nome = os.getenv("LLM_MODEL")
    chave = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    url = os.getenv("LLM_BASE_URL") or None
    if provedor == "ollama":
        chave = os.getenv("LLM_API_KEY") or "ollama"
        url = url or "http://localhost:11434/v1"
    if not nome or not chave or provedor not in {"openai", "ollama"}:
        return nome, provedor, None, chave, url

    from langchain_openai import ChatOpenAI

    opcoes = opcoes_llm()
    if provedor == "ollama":
        opcoes["use_responses_api"] = False
    prazo = timeout_llm()
    if timeout is not None:
        prazo = min(timeout, prazo)
    modelo = ChatOpenAI(model=nome, api_key=chave, base_url=url, timeout=prazo,
                        temperature=temperatura, max_retries=0, **opcoes)
    return nome, provedor, modelo, chave, url
