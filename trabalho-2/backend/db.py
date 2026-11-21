"""Armazenamento SQLite da API e dos caches das ferramentas."""

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

RAIZ = Path(__file__).resolve().parents[1]


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def conectar(caminho: str | None = None) -> sqlite3.Connection:
    destino = caminho or os.getenv("SQLITE_PATH") or str(RAIZ / "data" / "lance.sqlite")
    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(destino, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def inicializar_banco(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS partidas (
            id TEXT PRIMARY KEY, usuario TEXT, dados TEXT NOT NULL, analise TEXT
        );
        CREATE INDEX IF NOT EXISTS partidas_usuario ON partidas(usuario);
        CREATE TABLE IF NOT EXISTS lances (
            partida_id TEXT NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
            indice INTEGER NOT NULL, dados TEXT NOT NULL, PRIMARY KEY(partida_id, indice)
        );
        CREATE INDEX IF NOT EXISTS lance_posicao
            ON lances(json_extract(dados,'$.fen_antes'), json_extract(dados,'$.san'));
        CREATE TABLE IF NOT EXISTS explicacoes (
            fen TEXT NOT NULL, lance TEXT NOT NULL, perfil TEXT NOT NULL, dados TEXT NOT NULL,
            PRIMARY KEY(fen, lance, perfil)
        );
        CREATE TABLE IF NOT EXISTS tarefas (
            id TEXT PRIMARY KEY, partida_id TEXT NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
            status TEXT NOT NULL, inicio TEXT NOT NULL, atual INTEGER NOT NULL,
            total INTEGER NOT NULL, erro TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS tarefa_ativa ON tarefas(partida_id)
            WHERE status IN ('pendente', 'em_andamento');
        CREATE TABLE IF NOT EXISTS cache_mcp (
            chave TEXT PRIMARY KEY, criado REAL NOT NULL, dados TEXT NOT NULL
        );
    """)


def salvar_partida(conn, partida: dict) -> str:
    origem = partida.get("url") or partida.get("chave_pgn") or partida["pgn"]
    usuario = (partida.get("usuario") or "").casefold()
    chave = (origem, usuario, partida["cor_do_jogador"])
    id_ = sha256(json.dumps(chave, ensure_ascii=False).encode()).hexdigest()[:24]
    dados = {k: v for k, v in partida.items() if k != "chave_pgn"}
    with conn:
        conn.execute("INSERT INTO partidas(id, usuario, dados) VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING",
                     (id_, usuario, json.dumps(dados, ensure_ascii=False)))
    return id_


def obter_partida(conn, partida_id: str, perfil: str = "") -> dict | None:
    partida = conn.execute("SELECT * FROM partidas WHERE id=?", (partida_id,)).fetchone()
    if partida is None:
        return None
    registros = conn.execute("""
        SELECT l.dados, e.dados AS explicacao FROM lances l
        LEFT JOIN explicacoes e ON e.fen=json_extract(l.dados,'$.fen_antes')
            AND e.lance=json_extract(l.dados,'$.san') AND e.perfil=?
        WHERE l.partida_id=? ORDER BY l.indice
        """, (perfil, partida_id))
    lances = []
    for linha in registros:
        lance = json.loads(linha["dados"])
        lance["explicacao"] = json.loads(linha["explicacao"]) if linha["explicacao"] else None
        lances.append(lance)
    tarefa = conn.execute("SELECT status FROM tarefas WHERE partida_id=? ORDER BY rowid DESC LIMIT 1",
                          (partida_id,)).fetchone()
    return {"id": partida_id, **json.loads(partida["dados"]), "lances": lances,
            "status_analise": tarefa["status"] if tarefa else "pendente",
            "analise": partida["analise"]}


def salvar_analise(conn, partida_id: str, lances: list[dict], assinatura: str | None = None,
                   tarefa_id: str | None = None) -> None:
    with conn:
        conn.executemany("INSERT OR REPLACE INTO lances VALUES (?, ?, ?)",
                         ((partida_id, l["indice"], json.dumps(l, ensure_ascii=False)) for l in lances))
        if assinatura is not None:
            conn.execute("UPDATE partidas SET analise=? WHERE id=?", (assinatura, partida_id))
            if tarefa_id is not None:
                conn.execute("UPDATE tarefas SET status='concluida', atual=total WHERE id=?", (tarefa_id,))
        elif tarefa_id is not None and lances:
            conn.execute("UPDATE tarefas SET atual=? WHERE id=?", (lances[-1]["indice"], tarefa_id))


def salvar_explicacao(conn, fen: str, lance: str, explicacao: dict, perfil: str = "") -> None:
    with conn:
        conn.execute("INSERT OR REPLACE INTO explicacoes VALUES (?, ?, ?, ?)",
                     (fen, lance, perfil, json.dumps(explicacao, ensure_ascii=False)))


def obter_explicacao(conn, fen: str, lance: str, perfil: str) -> dict | None:
    item = conn.execute("SELECT dados FROM explicacoes WHERE fen=? AND lance=? AND perfil=?",
                        (fen, lance, perfil)).fetchone()
    return json.loads(item["dados"]) if item else None


def obter_lance_analisado(conn, fen: str, lance: str, assinatura: str) -> dict | None:
    item = conn.execute("""
        SELECT l.dados FROM lances l JOIN partidas p ON p.id=l.partida_id
        WHERE json_extract(l.dados,'$.fen_antes')=? AND json_extract(l.dados,'$.san')=? AND p.analise=?
        ORDER BY l.partida_id LIMIT 1
        """, (fen, lance, assinatura)).fetchone()
    return json.loads(item["dados"]) if item else None


def iniciar_tarefa(conn, id_partida: str, assinatura: str) -> tuple[str, bool]:
    conn.execute("BEGIN IMMEDIATE")
    with conn:
        partida = conn.execute("SELECT dados, analise FROM partidas WHERE id=?", (id_partida,)).fetchone()
        if partida is None:
            raise KeyError(id_partida)
        tarefa = conn.execute("""SELECT id, status FROM tarefas WHERE partida_id=?
            ORDER BY rowid DESC LIMIT 1""", (id_partida,)).fetchone()
        if tarefa and (tarefa["status"] in {"pendente", "em_andamento"} or partida["analise"] == assinatura):
            return tarefa["id"], False
        ativas = conn.execute("SELECT count(*) FROM tarefas WHERE status IN ('pendente','em_andamento')").fetchone()[0]
        if ativas >= 8:
            raise OverflowError("A fila de análises está cheia.")
        id_ = uuid4().hex
        total = json.loads(partida["dados"])["total_lances"]
        conn.execute("DELETE FROM lances WHERE partida_id=?", (id_partida,))
        conn.execute("UPDATE partidas SET analise=NULL WHERE id=?", (id_partida,))
        conn.execute("INSERT INTO tarefas VALUES (?, ?, 'pendente', ?, 0, ?, NULL)",
                     (id_, id_partida, agora(), total))
        return id_, True


def atualizar_tarefa(conn, tarefa_id: str, progresso: dict) -> None:
    with conn:
        conn.execute("UPDATE tarefas SET status=?, atual=?, erro=? WHERE id=?",
                     (progresso["status"], progresso["atual"], progresso.get("erro"), tarefa_id))


def obter_tarefa(conn, tarefa_id: str) -> dict | None:
    linha = conn.execute("SELECT * FROM tarefas WHERE id=?", (tarefa_id,)).fetchone()
    if not linha:
        return None
    atual, total = linha["atual"], linha["total"]
    return {"id": tarefa_id, "partida_id": linha["partida_id"], "status": linha["status"],
            "progresso": {"lance_atual": atual, "total_lances": total, "percentual": round(100 * atual / total, 1)},
            "iniciada_em": linha["inicio"], "erro": linha["erro"],
            "resultado": f"/api/partidas/{linha['partida_id']}" if linha["status"] == "concluida" else None}


def interromper_tarefas(conn) -> None:
    with conn:
        conn.execute("""UPDATE tarefas SET status='erro', erro='Análise interrompida. Inicie novamente.'
                     WHERE status IN ('pendente','em_andamento')""")


def partidas_analisadas(conn, usuario: str, perfil: str):
    ids = conn.execute("SELECT id FROM partidas WHERE usuario=? AND analise IS NOT NULL", (usuario.casefold(),))
    return [obter_partida(conn, linha["id"], perfil) for linha in ids]


def abrir_cache():
    """Abre o cache das ferramentas mesmo quando o servidor MCP roda sozinho."""
    conn = conectar()
    try:
        inicializar_banco(conn)
    except sqlite3.Error:
        conn.close()
        raise
    return closing(conn)
