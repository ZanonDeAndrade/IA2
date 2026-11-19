"""Acesso do backend às ferramentas MCP.

- MCP_URL definido (ex.: http://mcp:8001/mcp no Docker): conecta via HTTP.
- MCP_URL vazio: carrega o servidor no mesmo processo (transporte em memória),
  prático para desenvolver e testar sem subir dois serviços.
Nos dois casos a chamada passa pelo protocolo MCP e fica no log das ferramentas.
"""

from __future__ import annotations

import os
from typing import Any, Awaitable, Callable

from fastmcp import Client
from fastmcp.exceptions import ToolError


class ErroFerramenta(RuntimeError):
    """Erro devolvido por uma ferramenta, com mensagem para o usuário."""


def _alvo():
    url = os.getenv("MCP_URL", "").strip()
    if url:
        return url
    from mcp_server.server import mcp  # import tardio: só no modo em memória
    return mcp


def cliente() -> Client:
    return Client(_alvo(), timeout=float(os.getenv("MCP_TIMEOUT_S", "180")))


async def chamar(ferramenta: str, argumentos: dict[str, Any],
                 progresso: Callable[[float, float | None, str | None], Awaitable[None]] | None = None
                 ) -> Any:
    try:
        async with cliente() as c:
            r = await c.call_tool(ferramenta, argumentos, progress_handler=progresso)
    except ToolError as e:
        raise ErroFerramenta(str(e)) from e
    except (ConnectionError, OSError) as e:
        raise ErroFerramenta("Servidor MCP indisponível.") from e
    if r.data is not None:
        return r.data
    return r.structured_content
