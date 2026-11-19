"""Ferramenta `buscar_partidas`: cliente da API pública do Chess.com.

Regras da API (https://www.chess.com/news/view/published-data-api):
- Sem chave, mas exige um User-Agent com o nome do app e um contato
  (sem ele a resposta é 403). Configure CHESSCOM_USER_AGENT no .env.
- Requisições em série (uma por vez); 429 = muitas requisições, esperar.
- Partidas recentes podem levar até um dia para aparecer.

Os arquivos mensais são guardados em cache (SQLite): meses passados não mudam,
então ficam para sempre; o mês atual expira em CACHE_MES_ATUAL_S segundos.
"""

from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chess.pgn
import httpx

API = "https://api.chess.com/pub"
USER_AGENT_PADRAO = "lance-a-lance/0.1 (trabalho academico de IA II; defina CHESSCOM_USER_AGENT no .env)"
RITMOS = {"bullet", "blitz", "rapid", "daily"}
_RITMOS_PT = {"rápida": "rapid", "rapida": "rapid", "relâmpago": "blitz", "relampago": "blitz",
              "diária": "daily", "diaria": "daily", "por correspondência": "daily"}
CACHE_MES_ATUAL_S = 600
_USUARIO_VALIDO = re.compile(r"^[A-Za-z0-9_-]{2,40}$")


class ErroChessCom(RuntimeError):
    """Erro com mensagem clara para mostrar ao usuário."""


def _caminho_cache() -> Path:
    base = Path(os.getenv("CACHE_DIR", Path(__file__).resolve().parents[2] / "data" / "cache"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "chesscom.sqlite"


class ClienteChessCom:
    def __init__(self, transport: httpx.BaseTransport | None = None,
                 cache_path: Path | None = None, pausa_s: float = 0.2) -> None:
        self._http = httpx.Client(
            base_url=API, timeout=20, transport=transport, follow_redirects=True,
            headers={"User-Agent": os.getenv("CHESSCOM_USER_AGENT", USER_AGENT_PADRAO),
                     "Accept": "application/json"},
        )
        self._lock = threading.Lock()  # garante requisições em série
        self._pausa = pausa_s
        self._cache_path = cache_path or _caminho_cache()
        with self._con() as con:
            con.execute("CREATE TABLE IF NOT EXISTS respostas (url TEXT PRIMARY KEY, "
                        "corpo TEXT NOT NULL, salvo_em REAL NOT NULL, permanente INTEGER NOT NULL)")

    def _con(self) -> sqlite3.Connection:
        return sqlite3.connect(self._cache_path)

    # -- HTTP com cache ------------------------------------------------------ #
    def _get(self, caminho: str, permanente: bool) -> dict[str, Any]:
        with self._con() as con:
            linha = con.execute("SELECT corpo, salvo_em, permanente FROM respostas WHERE url = ?",
                                (caminho,)).fetchone()
        if linha and (linha[2] or time.time() - linha[1] < CACHE_MES_ATUAL_S):
            return json.loads(linha[0])

        with self._lock:
            for tentativa in range(3):
                try:
                    r = self._http.get(caminho)
                except httpx.HTTPError as e:
                    if linha:  # API fora do ar: usa o cache vencido
                        return json.loads(linha[0])
                    raise ErroChessCom(f"Não foi possível acessar a API do Chess.com ({e.__class__.__name__}).")
                if r.status_code == 429 and tentativa < 2:
                    time.sleep(2 * (tentativa + 1))
                    continue
                break
            time.sleep(self._pausa)

        if r.status_code == 404:
            raise ErroChessCom("Usuário não encontrado no Chess.com.")
        if r.status_code == 403:
            raise ErroChessCom("O Chess.com recusou a requisição (403). Confira CHESSCOM_USER_AGENT no .env.")
        if r.status_code == 429:
            raise ErroChessCom("Limite de requisições do Chess.com atingido. Tente de novo em instantes.")
        if r.status_code >= 400:
            if linha:
                return json.loads(linha[0])
            raise ErroChessCom(f"Erro {r.status_code} na API do Chess.com.")

        dados = r.json()
        with self._con() as con:
            con.execute("INSERT OR REPLACE INTO respostas VALUES (?,?,?,?)",
                        (caminho, json.dumps(dados), time.time(), int(permanente)))
        return dados

    def arquivos(self, usuario: str) -> list[str]:
        dados = self._get(f"/player/{usuario}/games/archives", permanente=False)
        return dados.get("archives", [])

    def partidas_do_mes(self, url_arquivo: str) -> list[dict[str, Any]]:
        caminho = url_arquivo.split("/pub", 1)[-1]
        ano, mes = (int(x) for x in caminho.rstrip("/").split("/")[-2:])
        agora = datetime.now(timezone.utc)
        mes_atual = (ano, mes) >= (agora.year, agora.month)
        return self._get(caminho, permanente=not mes_atual).get("games", [])


_cliente: ClienteChessCom | None = None


def cliente() -> ClienteChessCom:
    global _cliente
    if _cliente is None:
        _cliente = ClienteChessCom()
    return _cliente


# --------------------------------------------------------------------------- #
# Conversão de uma partida do Chess.com para o formato do projeto
# --------------------------------------------------------------------------- #

_RESULTADOS_EMPATE = {"agreed", "repetition", "stalemate", "insufficient",
                      "50move", "timevsinsufficient"}


def _resultado(codigo: str) -> str:
    if codigo == "win":
        return "vitoria"
    if codigo in _RESULTADOS_EMPATE:
        return "empate"
    return "derrota"


def _abertura(pgn: str, eco_url: str | None) -> str | None:
    if eco_url:
        nome = eco_url.rstrip("/").split("/")[-1]
        # corta a sequência de lances no fim da URL ("...-3...Bc5" ou "...5.d3-d6")
        nome = re.split(r"\.\.\.|-\d", nome)[0]
        return nome.replace("-", " ")
    m = re.search(r'\[ECO "([^"]+)"\]', pgn)
    return m.group(1) if m else None


def _numero_lances(pgn: str) -> int:
    jogo = chess.pgn.read_game(io.StringIO(pgn))
    if jogo is None:
        return 0
    n = sum(1 for _ in jogo.mainline_moves())
    return (n + 1) // 2


def _resultado_pgn(brancas: dict, pretas: dict) -> str:
    """Resultado no formato do PGN, a partir dos códigos da API (win, checkmated...)."""
    if brancas.get("result") == "win":
        return "1-0"
    if pretas.get("result") == "win":
        return "0-1"
    if brancas.get("result") in _RESULTADOS_EMPATE:
        return "1/2-1/2"
    return "*"


def converter(partida: dict[str, Any], usuario: str) -> dict[str, Any]:
    brancas, pretas = partida.get("white", {}), partida.get("black", {})
    jogador_brancas = brancas.get("username", "").lower() == usuario.lower()
    eu, ele = (brancas, pretas) if jogador_brancas else (pretas, brancas)
    pgn = partida.get("pgn", "")
    fim = partida.get("end_time")
    return {
        "id": "chesscom-" + partida.get("url", "").rstrip("/").split("/")[-1],
        "url": partida.get("url"),
        "data": datetime.fromtimestamp(fim, timezone.utc).date().isoformat() if fim else None,
        "data_hora": datetime.fromtimestamp(fim, timezone.utc).isoformat() if fim else None,
        "ritmo": partida.get("time_class"),
        "controle_de_tempo": partida.get("time_control"),
        "cor_do_jogador": "white" if jogador_brancas else "black",
        "adversario": ele.get("username"),
        "resultado": _resultado_pgn(brancas, pretas),
        "resultado_do_jogador": _resultado(eu.get("result", "")),
        "rating_do_jogador": eu.get("rating"),
        "rating_adversario": ele.get("rating"),
        "abertura": _abertura(pgn, partida.get("eco")),
        "total_lances": _numero_lances(pgn),
        "pgn": pgn,
    }


def buscar_partidas(usuario: str, max: int = 10, ritmo: str | None = None,
                    _cliente: ClienteChessCom | None = None) -> list[dict]:
    """Busca as últimas partidas concluídas de um usuário do Chess.com.

    Percorre os arquivos mensais do mais recente para o mais antigo até reunir
    ``max`` partidas de xadrez padrão (variantes como chess960 ficam de fora).

    Args:
        usuario: nome de usuário no Chess.com (perfil público).
        max: quantidade máxima de partidas (1 a 50, padrão 10).
        ritmo: ``"bullet"``, ``"blitz"``, ``"rapid"``, ``"daily"`` (ou em
            português: relâmpago, rápida, diária); ``None`` traz todos.

    Returns:
        Lista de partidas (da mais recente para a mais antiga) com ``id``,
        ``url``, ``data``, ``ritmo``, ``cor_do_jogador`` (white/black),
        ``adversario``, ``resultado`` (1-0, 0-1, 1/2-1/2), ``resultado_do_jogador``,
        ratings, ``abertura``, ``total_lances`` e ``pgn``.
    """
    usuario = (usuario or "").strip()
    if not _USUARIO_VALIDO.match(usuario):
        raise ErroChessCom("Nome de usuário do Chess.com inválido.")
    max_ = int(max)
    if not 1 <= max_ <= 50:
        raise ErroChessCom("max deve estar entre 1 e 50.")
    if ritmo:
        ritmo = _RITMOS_PT.get(ritmo.strip().lower(), ritmo.strip().lower())
        if ritmo not in RITMOS:
            raise ErroChessCom(f"Ritmo inválido. Use um destes: {', '.join(sorted(RITMOS))}.")

    cli = _cliente or cliente()
    encontradas: list[dict[str, Any]] = []
    for url in reversed(cli.arquivos(usuario.lower())):  # do mês mais recente para o mais antigo
        jogos = [j for j in cli.partidas_do_mes(url) if j.get("rules") == "chess" and j.get("pgn")]
        if ritmo:
            jogos = [j for j in jogos if j.get("time_class") == ritmo]
        jogos.sort(key=lambda j: j.get("end_time", 0), reverse=True)
        encontradas.extend(jogos)
        if len(encontradas) >= max_:
            break
    return [converter(j, usuario) for j in encontradas[:max_]]
