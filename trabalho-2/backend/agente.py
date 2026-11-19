"""Ponte entre a API e o agente (``agent/graph.py``, responsabilidade do Zanon).

O backend chama as funções do agente com as assinaturas definidas no esqueleto:

    explicar_erro(fen, lance_jogado, melhor_lance, linha_motor) -> dict
        {"tema", "texto", "ficha", "ferramentas_usadas", "tentativas", "validada"}
    responder_chat(fen, pergunta, historico) -> dict
        {"resposta", "ferramentas_usadas", "validada"}

Enquanto o agente lançar ``NotImplementedError`` (ou se ele falhar), a
explicação cai na explicação-padrão montada só com os dados do motor e do
python-chess (documentação, seção 8, passo 7), e o chat responde 503.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from backend import mcp_cliente
from mcp_server.tools.temas import rotulo

log = logging.getLogger("lance-a-lance.backend")

try:
    from agent import graph as _grafo
except Exception as e:  # noqa: BLE001 - dependências do agente podem faltar
    log.warning("Agente indisponível (%s); usando explicação-padrão do motor.", e)
    _grafo = None


class AgenteIndisponivel(RuntimeError):
    pass


async def _chamar(func, *args):
    if inspect.iscoroutinefunction(func):
        return await func(*args)
    return await asyncio.to_thread(func, *args)


def _pct(x: float) -> str:
    return f"{x:.0f}%"


_CLASSE_TEXTO = {"erro_grave": "um erro grave", "erro": "um erro",
                 "imprecisao": "uma imprecisão", "aceitavel": "um lance aceitável"}


def _tema_pelos_fatos(fatos: dict[str, Any]) -> str:
    """Tema aproximado a partir dos fatos da posição depois do erro (sem LLM).
    É o adversário quem joga: olhamos o que ele passou a ter disponível."""
    jogo = fatos.get("para_quem_joga", {})
    vez = fatos.get("vez")
    if jogo.get("mate_em_1"):
        return "mate"
    if jogo.get("garfos_possiveis"):
        return "garfo"
    if any(c["cor_atacante"] == vez for c in fatos.get("cravadas", [])):
        return "cravada"
    if any(e["cor_atacante"] == vez for e in fatos.get("espetos", [])):
        return "espeto"
    if any(p["pendurada"] and p["cor"] != vez for p in fatos.get("pecas_atacadas", [])):
        return "peca_pendurada"
    return "outro"


async def explicacao_padrao(ctx: dict[str, Any]) -> dict[str, Any]:
    """Explicação montada só com dados do motor e do python-chess (sem LLM)."""
    fatos = await mcp_cliente.chamar("descrever_posicao", {"fen": ctx["fen_depois"]})
    jogo = fatos["para_quem_joga"]
    resposta = ctx.get("melhor_resposta")

    partes = [
        f"{ctx['lance_jogado']} foi {_CLASSE_TEXTO.get(ctx['classe'], 'um lance')}: sua chance de "
        f"vitória caiu de {_pct(ctx['chance_antes'])} para {_pct(ctx['chance_depois'])}."
    ]
    # O tema vem do que a melhor resposta do adversário faz (fatos do python-chess).
    garfo = next((g for g in jogo["garfos_possiveis"] if g["lance"] == resposta), None)
    captura = next((c for c in jogo["capturas_possiveis"] if c["lance"] == resposta), None)
    if resposta and resposta in jogo["mate_em_1"]:
        tema = "mate"
        partes.append(f"Ele permite mate imediato com {resposta}.")
    elif garfo:
        tema = "garfo"
        partes.append(f"O adversário responde {resposta}, um garfo que ataca {' e '.join(garfo['ataca'][:2])}.")
    elif captura:
        tema = "peca_pendurada" if not captura["casa_defendida_pelo_adversario"] else _tema_pelos_fatos(fatos)
        partes.append(f"O adversário responde {resposta}, capturando seu {captura['captura']}.")
    else:
        tema = _tema_pelos_fatos(fatos)
        if resposta:
            partes.append(f"A melhor resposta do adversário é {resposta}.")
    if ctx.get("melhor_lance"):
        linha = " ".join(ctx.get("linha_motor", [])[:4])
        partes.append(f"O motor recomendava {ctx['melhor_lance']}" + (f" (linha: {linha})." if linha else "."))

    return {
        "tema": tema,
        "tema_label": rotulo(tema),
        "texto": " ".join(partes),
        "ficha": None,
        "ferramentas_usadas": ["analisar_partida", "descrever_posicao"],
        "tentativas": 0,
        "validada": True,  # só cita lances vindos do motor e do python-chess
        "origem": "motor",
    }


async def explicar_erro(ctx: dict[str, Any]) -> dict[str, Any]:
    """Modo 1 do agente; cai na explicação-padrão se o agente não existir ou falhar."""
    if _grafo is not None:
        try:
            r = await _chamar(_grafo.explicar_erro, ctx["fen_antes"], ctx["lance_jogado"],
                              ctx["melhor_lance"], ctx.get("linha_motor", []))
            tema = r.get("tema") or "outro"
            return {"tema_label": rotulo(tema), **r, "tema": tema, "origem": "agente"}
        except NotImplementedError:
            pass
        except Exception as e:  # noqa: BLE001
            log.exception("Agente falhou ao explicar; usando explicação-padrão: %s", e)
    return await explicacao_padrao(ctx)


async def conversar(fen: str, pergunta: str, historico: list[dict]) -> dict[str, Any]:
    """Modo 2 do agente (chat). Lança AgenteIndisponivel se ele ainda não existir."""
    if _grafo is None:
        raise AgenteIndisponivel("O chat ainda não está disponível: o agente não foi configurado.")
    try:
        return await _chamar(_grafo.responder_chat, fen, pergunta, historico)
    except NotImplementedError as e:
        raise AgenteIndisponivel("O chat ainda não está disponível: o agente ainda não foi implementado.") from e


def agente_disponivel() -> bool:
    """True quando agent/graph.py já implementa explicar_erro."""
    if _grafo is None:
        return False
    fonte = inspect.getsource(_grafo.explicar_erro)
    return "raise NotImplementedError" not in fonte
