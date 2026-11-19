"""Cache em SQLite: partidas importadas, análises e explicações já geradas.

Evita reprocessar partidas (RF11) e guarda o progresso das tarefas de análise.
O caminho do banco vem de ``DB_PATH`` (padrão ``data/lance_a_lance.sqlite``) e
os arquivos ``*.sqlite`` nunca entram no Git.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

RAIZ = Path(__file__).resolve().parents[1]

ESQUEMA = """
CREATE TABLE IF NOT EXISTS partidas (
    id TEXT PRIMARY KEY,
    usuario TEXT,                 -- usuário do Chess.com (minúsculo) ou NULL para PGN colado
    origem TEXT NOT NULL,         -- 'chesscom' | 'pgn'
    pgn TEXT NOT NULL,
    cor_do_jogador TEXT NOT NULL, -- 'white' | 'black'
    meta TEXT NOT NULL,           -- JSON: url, data, ritmo, adversario, resultado, abertura...
    importada_em REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_partidas_usuario ON partidas(usuario);

CREATE TABLE IF NOT EXISTS analises (
    partida_id TEXT PRIMARY KEY REFERENCES partidas(id),
    lances TEXT NOT NULL,         -- JSON devolvido por analisar_partida
    criada_em REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS explicacoes (
    chave TEXT PRIMARY KEY,       -- fen antes do lance + lance em UCI
    explicacao TEXT NOT NULL,
    criada_em REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tarefas (
    id TEXT PRIMARY KEY,
    partida_id TEXT NOT NULL,
    status TEXT NOT NULL,         -- pendente | em_andamento | concluida | erro
    etapa TEXT,                   -- analisando | explicando
    lance_atual INTEGER NOT NULL DEFAULT 0,
    total_lances INTEGER NOT NULL DEFAULT 0,
    erro TEXT,
    iniciada_em TEXT NOT NULL,
    atualizada_em REAL NOT NULL
);
"""


def caminho_db() -> Path:
    return Path(os.getenv("DB_PATH", RAIZ / "data" / "lance_a_lance.sqlite"))


@contextmanager
def conectar() -> Iterator[sqlite3.Connection]:
    caminho = caminho_db()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def inicializar_banco() -> None:
    """Cria as tabelas e marca como erro as tarefas interrompidas por um reinício."""
    with conectar() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(ESQUEMA)
        con.execute("UPDATE tarefas SET status='erro', erro='Servidor reiniciado durante a análise' "
                    "WHERE status IN ('pendente','em_andamento')")


# -- partidas -------------------------------------------------------------------

_COLUNAS = {"id", "usuario", "origem", "pgn", "cor_do_jogador"}


def salvar_partida(p: dict[str, Any]) -> str:
    meta = {k: v for k, v in p.items() if k not in _COLUNAS}
    with conectar() as con:
        con.execute(
            "INSERT INTO partidas VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET meta=excluded.meta",
            (p["id"], p.get("usuario"), p["origem"], p["pgn"], p["cor_do_jogador"],
             json.dumps(meta, ensure_ascii=False), time.time()),
        )
    return p["id"]


def _partida(linha: sqlite3.Row) -> dict[str, Any]:
    return {**json.loads(linha["meta"]), "id": linha["id"], "usuario": linha["usuario"],
            "origem": linha["origem"], "pgn": linha["pgn"], "cor_do_jogador": linha["cor_do_jogador"]}


def obter_partida(partida_id: str) -> dict[str, Any] | None:
    with conectar() as con:
        linha = con.execute("SELECT * FROM partidas WHERE id = ?", (partida_id,)).fetchone()
    return _partida(linha) if linha else None


def partidas_do_usuario(usuario: str) -> list[dict[str, Any]]:
    with conectar() as con:
        linhas = con.execute("SELECT * FROM partidas WHERE usuario = ?", (usuario.lower(),)).fetchall()
    partidas = [_partida(l) for l in linhas]
    partidas.sort(key=lambda p: p.get("data_hora") or p.get("data") or "", reverse=True)
    return partidas


# -- análises -------------------------------------------------------------------

def salvar_analise(partida_id: str, lances: list[dict]) -> None:
    with conectar() as con:
        con.execute("INSERT OR REPLACE INTO analises VALUES (?,?,?)",
                    (partida_id, json.dumps(lances, ensure_ascii=False), time.time()))


def obter_analise(partida_id: str) -> list[dict] | None:
    with conectar() as con:
        linha = con.execute("SELECT lances FROM analises WHERE partida_id = ?", (partida_id,)).fetchone()
    return json.loads(linha["lances"]) if linha else None


# -- explicações ----------------------------------------------------------------

def chave_explicacao(fen: str, lance_uci: str) -> str:
    return f"{fen}|{lance_uci}"


def salvar_explicacao(fen: str, lance_uci: str, explicacao: dict[str, Any]) -> None:
    with conectar() as con:
        con.execute("INSERT OR REPLACE INTO explicacoes VALUES (?,?,?)",
                    (chave_explicacao(fen, lance_uci), json.dumps(explicacao, ensure_ascii=False), time.time()))


def obter_explicacao(fen: str, lance_uci: str) -> dict[str, Any] | None:
    with conectar() as con:
        linha = con.execute("SELECT explicacao FROM explicacoes WHERE chave = ?",
                            (chave_explicacao(fen, lance_uci),)).fetchone()
    return json.loads(linha["explicacao"]) if linha else None


# -- tarefas --------------------------------------------------------------------

def criar_tarefa(partida_id: str) -> dict[str, Any]:
    tarefa_id = "tarefa-" + uuid.uuid4().hex[:10]
    with conectar() as con:
        con.execute("INSERT INTO tarefas VALUES (?,?,?,?,?,?,?,?,?)",
                    (tarefa_id, partida_id, "pendente", None, 0, 0, None,
                     datetime.now().astimezone().isoformat(timespec="seconds"), time.time()))
    return obter_tarefa(tarefa_id)


def atualizar_tarefa(tarefa_id: str, **campos: Any) -> None:
    campos["atualizada_em"] = time.time()
    sets = ", ".join(f"{k} = ?" for k in campos)
    with conectar() as con:
        con.execute(f"UPDATE tarefas SET {sets} WHERE id = ?", (*campos.values(), tarefa_id))


def obter_tarefa(tarefa_id: str) -> dict[str, Any] | None:
    """Tarefa no formato de ``frontend/src/mocks/tarefa.json``."""
    with conectar() as con:
        t = con.execute("SELECT * FROM tarefas WHERE id = ?", (tarefa_id,)).fetchone()
    if not t:
        return None
    total = t["total_lances"]
    return {
        "id": t["id"],
        "tarefa_id": t["id"],
        "partida_id": t["partida_id"],
        "status": t["status"],
        "etapa": t["etapa"],
        "progresso": {
            "lance_atual": t["lance_atual"],
            "total_lances": total,
            "percentual": round(100 * t["lance_atual"] / total, 1) if total else 0.0,
        },
        "iniciada_em": t["iniciada_em"],
        "erro": t["erro"],
    }


def ultima_tarefa(partida_id: str) -> dict[str, Any] | None:
    with conectar() as con:
        linha = con.execute("SELECT id FROM tarefas WHERE partida_id = ? ORDER BY atualizada_em DESC LIMIT 1",
                            (partida_id,)).fetchone()
    return obter_tarefa(linha["id"]) if linha else None
