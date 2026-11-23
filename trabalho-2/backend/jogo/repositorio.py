"""Reservas curtas e gravação atômica do turno no SQLite."""

import json
from collections.abc import Callable
from contextlib import closing, contextmanager
from hashlib import sha256
from sqlite3 import Connection
from time import time
from uuid import uuid4

from fastapi import HTTPException

from backend import db
from backend.jogo.modelos import JogoSalvo

PRAZO_MOTOR = 45
PRAZO_RESERVA = PRAZO_MOTOR + 15
AgendarExplicacao = Callable[[Connection, JogoSalvo], None]


def perfil_da_sessao(sessao: str | None) -> str | None:
    if sessao is None:
        return None
    perfil = sha256(f"progresso:{sessao}".encode()).hexdigest()[:40]
    return f"treino-{perfil}"


def obter(id_: str) -> tuple[JogoSalvo, bool]:
    with closing(db.conectar()) as conn:
        registro = conn.execute("SELECT dados, reservada_ate FROM jogos WHERE id=?", (id_,)).fetchone()
    if registro is None:
        raise HTTPException(404, "Partida contra o Stockfish não encontrada.")
    return JogoSalvo.model_validate_json(registro["dados"]), (registro["reservada_ate"] or 0) > time()


def criar(jogo: JogoSalvo, sessao: str | None = None) -> None:
    with closing(db.conectar()) as conn, conn:
        conn.execute("INSERT INTO jogos(id, versao, dados) VALUES (?, ?, ?)",
                     (jogo.id, jogo.versao, jogo.model_dump_json()))
        if sessao is not None:
            conn.execute("INSERT INTO jogos_sessoes(jogo_id, sessao_hash) VALUES (?, ?)",
                         (jogo.id, sha256(sessao.encode()).hexdigest()))


def listar(sessao: str, limite: int, deslocamento: int) -> list[dict]:
    with closing(db.conectar()) as conn:
        registros = conn.execute("""
            SELECT j.id, json_extract(j.dados, '$.criado_em') AS criado_em,
                   json_extract(j.dados, '$.cor_do_jogador') AS cor_do_jogador,
                   json_extract(j.dados, '$.dificuldade') AS dificuldade,
                   json_extract(j.dados, '$.status') AS status,
                   json_extract(j.dados, '$.resultado') AS resultado,
                   json_extract(j.dados, '$.partida_analise_id') AS partida_analise_id
            FROM jogos_sessoes s JOIN jogos j ON j.id=s.jogo_id
            WHERE s.sessao_hash=? ORDER BY j.rowid DESC LIMIT ? OFFSET ?
        """, (sha256(sessao.encode()).hexdigest(), limite, deslocamento))
        return [dict(registro) for registro in registros]


def avaliacao_da_revisao(partida_id: str, indice: int, perfil: str) -> dict | None:
    with closing(db.conectar()) as conn:
        registro = conn.execute("""
            SELECT l.dados FROM lances l JOIN partidas p ON p.id=l.partida_id
            WHERE l.partida_id=? AND l.indice=? AND p.analise=?
        """, (partida_id, indice, perfil)).fetchone()
    return {**json.loads(registro["dados"]), "perfil_analise": perfil} if registro else None


@contextmanager
def reservar(id_: str, versao: int):
    token = uuid4().hex
    agora = time()
    with closing(db.conectar()) as conn, conn:
        registro = conn.execute("""
            UPDATE jogos SET reserva=?, reservada_ate=?
            WHERE id=? AND versao=? AND (reserva IS NULL OR reservada_ate <= ?)
            RETURNING dados
        """, (token, agora + PRAZO_RESERVA, id_, versao, agora)).fetchone()
        if registro is None:
            if conn.execute("SELECT 1 FROM jogos WHERE id=?", (id_,)).fetchone() is None:
                raise HTTPException(404, "Partida contra o Stockfish não encontrada.")
            raise HTTPException(409, "A versão mudou ou há um turno em processamento. Atualize a partida.")
    try:
        yield JogoSalvo.model_validate_json(registro["dados"]), token
    finally:
        with closing(db.conectar()) as conn, conn:
            conn.execute("UPDATE jogos SET reserva=NULL, reservada_ate=NULL WHERE id=? AND reserva=?", (id_, token))


def confirmar(jogo: JogoSalvo, token: str, revisao: dict | None = None,
              *, agendar: AgendarExplicacao | None = None) -> None:
    with closing(db.conectar()) as conn, conn:
        if revisao is not None:
            jogo.partida_analise_id = db.registrar_partida(conn, revisao)
        elif jogo.partida_analise_id is not None:
            # Uma avaliação solicitada após o fim acrescenta comentários ao mesmo PGN de revisão.
            conn.execute("UPDATE partidas SET dados=json_set(dados, '$.pgn', ?) WHERE id=?",
                         (jogo.pgn, jogo.partida_analise_id))
        atualizacao = conn.execute("""
            UPDATE jogos SET versao=?, dados=?, reserva=NULL, reservada_ate=NULL
            WHERE id=? AND reserva=? AND versao=? AND reservada_ate > ?
        """, (jogo.versao, jogo.model_dump_json(), jogo.id, token, jogo.versao - 1, time()))
        if atualizacao.rowcount != 1:
            raise HTTPException(409, "A reserva do turno expirou. Atualize a partida.")
        if agendar is not None:
            agendar(conn, jogo)
