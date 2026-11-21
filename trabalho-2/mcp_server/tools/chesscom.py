"""Importação somente leitura da API pública do Chess.com."""

import json
import os
import re
from datetime import datetime, timezone
from threading import Lock
from time import monotonic, time
from urllib.parse import unquote, urlsplit

import httpx
from fastmcp.exceptions import ToolError

from backend.db import abrir_cache
from mcp_server.tools.pgn import USUARIO, ler_partida, metadados

BASE = "https://api.chess.com/pub/player"
RITMOS = {"bullet", "blitz", "rapid", "daily"}
_SERIE = Lock()


def _consultar(conn, cliente, url: str, campo: str, validade: int) -> list:
    cache = conn.execute("SELECT criado, dados FROM cache_mcp WHERE chave=?", (url,)).fetchone()
    if cache and time() - cache["criado"] < validade:
        return json.loads(cache["dados"])
    try:
        resposta = cliente.get(url)
        if resposta.status_code == 404 and campo == "archives":
            raise ToolError("CHESSCOM_USUARIO_INEXISTENTE")
        resposta.raise_for_status()
        dados = resposta.json()[campo]
        if not isinstance(dados, list):
            raise ValueError("Formato inválido.")
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as erro:
        if cache:
            return json.loads(cache["dados"])
        raise ToolError("CHESSCOM_INDISPONIVEL") from erro
    with conn:
        conn.execute("INSERT OR REPLACE INTO cache_mcp VALUES (?, ?, ?)", (url, time(), json.dumps(dados)))
    return dados


def _partida(raw: dict, usuario: str) -> dict | None:
    try:
        pgn = raw["pgn"]
        jogo = ler_partida(pgn)
        jogadores = {cor: raw[cor] for cor in ("white", "black")}
        cor = next(lado for lado, dados in jogadores.items() if dados["username"].casefold() == usuario)
        partida = metadados(jogo, pgn, usuario, cor)
        abertura_url = jogo.headers.get("ECOUrl", "")
        if not jogo.headers.get("Opening") and abertura_url.startswith("https://www.chess.com/openings/"):
            partida["abertura"] = unquote(urlsplit(abertura_url).path.rsplit("/", 1)[-1]).replace("-", " ")
        partida["jogadores"] = {
            lado: {"nome": dados["username"], "rating": dados.get("rating"), "resultado": dados.get("result")}
            for lado, dados in jogadores.items()
        }
        url = raw["url"]
        if not isinstance(url, str) or not url.startswith("https://www.chess.com/game/"):
            return None
        data = datetime.fromtimestamp(raw["end_time"], timezone.utc).date().isoformat()
        partida.update(url=url, data=data, ritmo=raw["time_class"],
                       adversario=jogadores["black" if cor == "white" else "white"]["username"])
        return partida
    except (AttributeError, KeyError, OSError, OverflowError, TypeError, ValueError, StopIteration):
        return None


def buscar_partidas(usuario: str, max: int = 10, ritmo: str | None = None) -> list[dict]:
    """Busca até N partidas concluídas de xadrez padrão, da mais recente à mais antiga."""
    if not USUARIO.fullmatch(usuario) or not 1 <= max <= 50 or ritmo is not None and ritmo not in RITMOS:
        raise ValueError("Usuário, quantidade ou ritmo inválido.")
    agente = (os.getenv("CHESSCOM_USER_AGENT") or "").strip()
    if not agente:
        raise ToolError("CHESSCOM_USER_AGENT_AUSENTE")
    if not _SERIE.acquire(timeout=5):
        raise ToolError("CHESSCOM_INDISPONIVEL")
    prazo = monotonic() + 32
    try:
        usuario = usuario.lower()
        prefixo = f"{BASE}/{usuario}/games"
        padrao = re.compile(re.escape(prefixo) + r"/\d{4}/(?:0[1-9]|1[0-2])")
        with abrir_cache() as conn, httpx.Client(headers={"User-Agent": agente}, timeout=5) as cliente:
            arquivos = _consultar(conn, cliente, prefixo + "/archives", "archives", 3600)
            resultado, urls = [], set()
            mes_atual = datetime.now(timezone.utc).strftime("%Y/%m")
            meses = {url for url in arquivos if isinstance(url, str) and padrao.fullmatch(url)}
            for mes in sorted(meses, reverse=True):
                if monotonic() >= prazo:
                    raise ToolError("CHESSCOM_INDISPONIVEL")
                validade = 3600 if mes.endswith(mes_atual) else 7 * 86400
                if jogos := _consultar(conn, cliente, mes, "games", validade):
                    elegiveis = (raw for raw in jogos if isinstance(raw, dict) and
                                 type(raw.get("end_time")) is int and raw.get("rules") == "chess" and
                                 (ritmo is None or raw.get("time_class") == ritmo))
                    for raw in sorted(elegiveis, key=lambda item: item["end_time"], reverse=True):
                        partida = _partida(raw, usuario)
                        if partida and partida["url"] not in urls:
                            resultado.append(partida)
                            urls.add(partida["url"])
                            if len(resultado) == max:
                                return resultado
            return resultado
    finally:
        _SERIE.release()
