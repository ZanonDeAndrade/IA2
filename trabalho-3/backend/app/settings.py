"""Configuração do backend lida do ambiente (.env). Nenhum segredo é necessário no MVP.

Variáveis documentadas em docs/10-development/setup.md (.env.example) e backend/README.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"
    ollama_timeout: float = 120.0  # por chamada ao /api/chat (CPU pode ser lenta)
    ollama_temperature: float = 0.2
    ollama_num_ctx: int = 8192
    ollama_num_predict: int = 1024
    # qwen3 é um modelo "thinking"; desligar reduz latência. None = não enviar o parâmetro.
    ollama_think: bool | None = False

    max_tool_calls: int = 6  # por turno (mcp-server.md e .env.example; architecture.md cita 4)
    max_llm_rounds: int = 8  # rodadas LLM por turno (impede loop mesmo sem tool calls)
    inference_timeout: float = 300.0  # prazo total de uma consulta

    max_question_chars: int = 500
    min_question_chars: int = 3
    max_ingredients: int = 30
    max_ingredient_chars: int = 80
    max_recipes: int = 5

    # Camada HTTP (prompt 27): origens do frontend autorizadas no CORS (CORS_ORIGINS, separadas por vírgula).
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    max_body_bytes: int = 16_384  # corpo de /api/v1/consultations; o guardrail valida os campos

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ.get
        think_raw = env("OLLAMA_THINK")
        think: bool | None
        if think_raw is not None and think_raw.strip().lower() in {"none", "omit", ""}:
            think = None
        else:
            think = _bool(think_raw, False)
        return cls(
            ollama_base_url=env("OLLAMA_BASE_URL", cls.ollama_base_url).rstrip("/"),
            ollama_model=env("OLLAMA_MODEL", cls.ollama_model),
            ollama_timeout=float(env("OLLAMA_TIMEOUT", cls.ollama_timeout)),
            ollama_temperature=float(env("OLLAMA_TEMPERATURE", cls.ollama_temperature)),
            ollama_num_ctx=int(env("OLLAMA_NUM_CTX", cls.ollama_num_ctx)),
            ollama_num_predict=int(env("OLLAMA_NUM_PREDICT", cls.ollama_num_predict)),
            ollama_think=think,
            max_tool_calls=int(env("MAX_TOOL_CALLS", cls.max_tool_calls)),
            max_llm_rounds=int(env("MAX_LLM_ROUNDS", cls.max_llm_rounds)),
            inference_timeout=float(env("INFERENCE_TIMEOUT", cls.inference_timeout)),
            cors_origins=_origins(env("CORS_ORIGINS"), cls.cors_origins),
        )


def _origins(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None or not value.strip():
        return default
    return tuple(o.strip().rstrip("/") for o in value.split(",") if o.strip())
