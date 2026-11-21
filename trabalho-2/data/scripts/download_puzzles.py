"""Prepara um recorte do CSV público e publica o SQLite depois de validá-lo."""

import argparse
import csv
import io
import json
from itertools import islice
from pathlib import Path
import random
import re
import sqlite3
import tempfile
from contextlib import closing

import chess
import httpx
import zstandard

from mcp_server.tools.puzzles import PADRAO, ROTULOS, TAGS

URL_BASE_PUZZLES = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
CAMINHO_SQLITE_PADRAO = str(PADRAO)
SNAPSHOT = PADRAO.parents[1] / "evaluation" / "lichess_candidatos.jsonl"


def baixar_base(destino: str) -> str:
    caminho = Path(destino)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    parcial = caminho.with_suffix(caminho.suffix + ".part")
    try:
        with httpx.stream("GET", URL_BASE_PUZZLES, timeout=30, follow_redirects=True) as resposta:
            resposta.raise_for_status()
            with parcial.open("wb") as arquivo:
                for bloco in resposta.iter_bytes(1024 * 1024):
                    arquivo.write(bloco)
        parcial.replace(caminho)
    finally:
        parcial.unlink(missing_ok=True)
    return str(caminho)


def recortar(caminho_zst: str, rating_min: int, rating_max: int, quantidade: int, prefixo: int | None = None):
    """Amostra determinística com cotas dos temas principais e complemento geral."""
    rng = random.Random(20261119)
    amostra, contagem = {}, {}
    geral = []
    total = 0
    estratos = sorted(set(TAGS.values()))
    teto = max(1, quantidade // (len(estratos) + 1))
    with open(caminho_zst, "rb") as fonte, zstandard.ZstdDecompressor().stream_reader(fonte) as dados:
        leitor = csv.DictReader(io.TextIOWrapper(dados, encoding="utf-8", newline=""))
        for row in islice(leitor, prefixo):
            rating = row.get("Rating", "")
            if not rating.isdecimal() or not rating_min <= int(rating) <= rating_max:
                continue
            total += 1
            if len(geral) < quantidade:
                geral.append(row)
            elif (indice := rng.randrange(total)) < quantidade:
                geral[indice] = row
            tags = set(row["Themes"].split())
            estrato = next((tag for tag in estratos if tag in tags), None)
            if estrato is None:
                continue
            grupo = amostra.setdefault(estrato, [])
            contagem[estrato] = contagem.get(estrato, 0) + 1
            if len(grupo) < teto:
                grupo.append(row)
            elif (indice := rng.randrange(contagem[estrato])) < teto:
                grupo[indice] = row
    escolhidos = {}
    for row in [*(row for tag in estratos for row in amostra.get(tag, [])), *geral]:
        escolhidos[row["PuzzleId"]] = row
        if len(escolhidos) == quantidade:
            break
    return list(escolhidos.values())


def _puzzle(row: dict) -> dict:
    id_ = row["PuzzleId"]
    if not re.fullmatch(r"[A-Za-z0-9]+", id_):
        raise ValueError("Identificador de puzzle inválido.")
    original = row["FEN"]
    tabuleiro = chess.Board(original)
    movimentos = row["Moves"].split()
    if not tabuleiro.is_valid() or len(movimentos) < 2:
        raise ValueError("Posição de puzzle inválida.")
    for indice, uci in enumerate(movimentos):
        lance = tabuleiro.parse_uci(uci)
        if not lance:
            raise ValueError("Lance nulo no puzzle.")
        tabuleiro.push(lance)
        if indice == 0:
            fen = tabuleiro.fen()
    temas = list(dict.fromkeys(row["Themes"].split()))
    return {"id": id_, "fen": fen, "fen_origem": original, "lance_preparatorio": movimentos[0],
            "solucao": movimentos[1:], "rating": int(row["Rating"]), "temas": temas,
            "temas_label": [ROTULOS.get(tema, tema) for tema in temas],
            "url": f"https://lichess.org/training/{id_}"}


def salvar_sqlite(recorte, caminho_sqlite: str = CAMINHO_SQLITE_PADRAO, origem: str = URL_BASE_PUZZLES) -> int:
    destino = Path(caminho_sqlite)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destino.parent, delete=False) as arquivo:
        caminho = Path(arquivo.name)
    try:
        with closing(sqlite3.connect(caminho)) as conn, conn:
            conn.executescript("""
                CREATE TABLE puzzles(id TEXT PRIMARY KEY, rating INTEGER NOT NULL, dados TEXT NOT NULL);
                CREATE TABLE temas(puzzle_id TEXT NOT NULL REFERENCES puzzles(id), tema TEXT NOT NULL,
                                   PRIMARY KEY(puzzle_id, tema));
                CREATE TABLE origem(fonte TEXT NOT NULL);
                CREATE INDEX puzzles_rating ON puzzles(rating);
                CREATE INDEX temas_por_tag ON temas(tema, puzzle_id);
            """)
            conn.execute("INSERT INTO origem VALUES (?)", (origem,))
            for row in recorte:
                try:
                    puzzle = _puzzle(row)
                except (KeyError, ValueError, TypeError):
                    continue
                cursor = conn.execute("INSERT OR IGNORE INTO puzzles VALUES (?, ?, ?)",
                                      (puzzle["id"], puzzle["rating"], json.dumps(puzzle, ensure_ascii=False)))
                if cursor.rowcount:
                    conn.executemany("INSERT INTO temas VALUES (?, ?)", ((puzzle["id"], tag) for tag in puzzle["temas"]))
            total = conn.execute("SELECT count(*) FROM puzzles").fetchone()[0]
            if total == 0:
                raise ValueError("O recorte não contém puzzles válidos.")
        caminho.replace(destino)
        return total
    finally:
        caminho.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    origens = parser.add_mutually_exclusive_group()
    origens.add_argument("--arquivo", help="CSV.zst já baixado")
    origens.add_argument("--recorte-versionado", action="store_true", help="Usa o recorte público rastreado na avaliação.")
    parser.add_argument("--download", default=str(PADRAO.with_name("lichess_db_puzzle.csv.zst")))
    parser.add_argument("--saida", default=CAMINHO_SQLITE_PADRAO)
    parser.add_argument("--rating-min", type=int, default=600)
    parser.add_argument("--rating-max", type=int, default=2200)
    parser.add_argument("--quantidade", type=int, default=50_000)
    parser.add_argument("--prefixo", type=int, help="Examina apenas este número de entradas do CSV.")
    args = parser.parse_args()
    if not 0 <= args.rating_min <= args.rating_max <= 4000 or args.quantidade < 1 or (args.prefixo or 1) < 1:
        parser.error("Faixa de rating, prefixo ou tamanho inválidos.")
    if args.recorte_versionado:
        with SNAPSHOT.open(encoding="utf-8") as fonte:
            dados = [json.loads(linha)["row"] for linha in fonte]
        selecionados = {row["PuzzleId"]: row for row in dados
                        if args.rating_min <= int(row["Rating"]) <= args.rating_max}
        total = salvar_sqlite(islice(selecionados.values(), args.quantidade), args.saida,
                              "evaluation/lichess_candidatos.jsonl")
    else:
        caminho_zst = args.arquivo or baixar_base(args.download)
        total = salvar_sqlite(recortar(caminho_zst, args.rating_min, args.rating_max, args.quantidade, args.prefixo), args.saida)
    print(f"{total} puzzles reais em {args.saida}")


if __name__ == "__main__":
    main()
