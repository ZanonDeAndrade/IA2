"""Baixa a base aberta de puzzles da Lichess e salva um recorte em SQLite.

A base completa (lichess_db_puzzle.csv.zst) tem ~300 MB compactada e milhões de
linhas. O script lê o arquivo em streaming (sem salvar o .zst em disco),
filtra por rating e popularidade e guarda uma amostra aleatória
(reservoir sampling) de N puzzles.

Uso:
    python data/scripts/download_puzzles.py                 # 50 mil puzzles, rating 600-2200
    python data/scripts/download_puzzles.py --quantidade 20000 --rating-min 800
    python data/scripts/download_puzzles.py --arquivo lichess_db_puzzle.csv.zst  # usa arquivo local
    python data/scripts/download_puzzles.py --max-linhas 300000      # download lento: só o começo

Licença dos dados: CC0 (domínio público) - https://database.lichess.org/#puzzles
"""

from __future__ import annotations

import argparse
import csv
import io
import random
import sqlite3
import sys
import time
from pathlib import Path

import httpx
import zstandard

URL_PADRAO = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
RAIZ = Path(__file__).resolve().parents[2]
SAIDA_PADRAO = RAIZ / "data" / "puzzles.sqlite"


def _linhas_csv(fluxo_binario) -> csv.DictReader:
    dctx = zstandard.ZstdDecompressor()
    leitor = dctx.stream_reader(fluxo_binario)
    texto = io.TextIOWrapper(leitor, encoding="utf-8", newline="")
    return csv.DictReader(texto)


class _FluxoHttp(io.RawIOBase):
    """Adapta um download httpx em streaming para um objeto de arquivo binário."""

    def __init__(self, resposta: httpx.Response):
        self._iter = resposta.iter_bytes(chunk_size=1 << 20)
        self._buffer = b""
        self.baixado = 0
        self.total = int(resposta.headers.get("content-length", 0))

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        while not self._buffer:
            try:
                self._buffer = next(self._iter)
                self.baixado += len(self._buffer)
            except StopIteration:
                return 0
        n = min(len(b), len(self._buffer))
        b[:n] = self._buffer[:n]
        self._buffer = self._buffer[n:]
        return n


def _seguro(linhas):
    """Para de ler sem erro se o .zst estiver incompleto (download parcial)."""
    try:
        yield from linhas
    except (zstandard.ZstdError, csv.Error, EOFError, UnicodeDecodeError) as e:
        print(f"  arquivo terminou antes do fim ({e.__class__.__name__}); usando o que foi lido",
              file=sys.stderr)


def amostrar(linhas, quantidade: int, rating_min: int, rating_max: int,
             popularidade_min: int, jogadas_min: int, semente: int,
             progresso=None, max_linhas: int | None = None) -> tuple[list[dict], int]:
    """Reservoir sampling: amostra uniforme de `quantidade` linhas válidas.

    `max_linhas` limita quantas linhas são lidas. A base vem ordenada pelo
    PuzzleId (aleatório), então o começo do arquivo já é uma amostra
    representativa - útil quando o download é lento.
    """
    rng = random.Random(semente)
    reservatorio: list[dict] = []
    validos = 0
    for i, linha in enumerate(_seguro(linhas)):
        if max_linhas and i >= max_linhas:
            break
        if progresso and i % 200_000 == 0:
            progresso(i, validos)
        try:
            rating = int(linha["Rating"])
            popularidade = int(linha["Popularity"])
            jogadas = int(linha["NbPlays"])
        except (KeyError, ValueError):
            continue
        if not (rating_min <= rating <= rating_max):
            continue
        if popularidade < popularidade_min or jogadas < jogadas_min:
            continue
        validos += 1
        if len(reservatorio) < quantidade:
            reservatorio.append(linha)
        else:
            j = rng.randrange(validos)
            if j < quantidade:
                reservatorio[j] = linha
    return reservatorio, validos


def salvar(puzzles: list[dict], destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(
        """
        CREATE TABLE puzzles (
            id TEXT PRIMARY KEY,
            fen TEXT NOT NULL,          -- posição ANTES do lance do adversário
            moves TEXT NOT NULL,        -- lances em UCI; o 1º é o do adversário
            rating INTEGER NOT NULL,
            rating_deviation INTEGER,
            popularity INTEGER,
            nb_plays INTEGER,
            themes TEXT NOT NULL,       -- temas em inglês separados por espaço
            game_url TEXT,
            opening_tags TEXT
        );
        CREATE TABLE puzzle_temas (
            puzzle_id TEXT NOT NULL REFERENCES puzzles(id),
            tema TEXT NOT NULL
        );
        """
    )
    con.executemany(
        "INSERT INTO puzzles VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (
                p["PuzzleId"], p["FEN"], p["Moves"], int(p["Rating"]),
                int(p["RatingDeviation"] or 0), int(p["Popularity"]),
                int(p["NbPlays"]), p["Themes"], p.get("GameUrl", ""),
                p.get("OpeningTags", ""),
            )
            for p in puzzles
        ],
    )
    con.executemany(
        "INSERT INTO puzzle_temas VALUES (?,?)",
        [(p["PuzzleId"], t) for p in puzzles for t in p["Themes"].split()],
    )
    con.executescript(
        """
        CREATE INDEX idx_temas_tema ON puzzle_temas(tema, puzzle_id);
        CREATE INDEX idx_puzzles_rating ON puzzles(rating);
        """
    )
    con.commit()
    con.close()
    tmp.replace(destino)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=URL_PADRAO)
    ap.add_argument("--arquivo", type=Path, help="usar um .csv.zst já baixado em vez da URL")
    ap.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    ap.add_argument("--quantidade", type=int, default=50_000)
    ap.add_argument("--rating-min", type=int, default=600)
    ap.add_argument("--rating-max", type=int, default=2200)
    ap.add_argument("--popularidade-min", type=int, default=50,
                    help="descarta puzzles mal avaliados (Popularity vai de -100 a 100)")
    ap.add_argument("--jogadas-min", type=int, default=100)
    ap.add_argument("--semente", type=int, default=42)
    ap.add_argument("--max-linhas", type=int, default=None,
                    help="lê só as primeiras N linhas (ex.: 300000 para download lento)")
    args = ap.parse_args(argv)

    inicio = time.time()

    def progresso_factory(fluxo=None):
        def progresso(i, validos):
            extra = ""
            if fluxo is not None and fluxo.total:
                extra = f" | {fluxo.baixado / fluxo.total:5.1%} baixado"
            print(f"  {i:>9,} linhas lidas, {validos:>9,} válidas{extra}", file=sys.stderr, flush=True)
        return progresso

    if args.arquivo:
        print(f"Lendo {args.arquivo} ...", file=sys.stderr)
        with open(args.arquivo, "rb") as f:
            puzzles, validos = amostrar(_linhas_csv(f), args.quantidade, args.rating_min,
                                        args.rating_max, args.popularidade_min,
                                        args.jogadas_min, args.semente, progresso_factory(),
                                        args.max_linhas)
    else:
        print(f"Baixando {args.url} em streaming ...", file=sys.stderr)
        with httpx.stream("GET", args.url, follow_redirects=True, timeout=60) as r:
            r.raise_for_status()
            fluxo = _FluxoHttp(r)
            puzzles, validos = amostrar(_linhas_csv(io.BufferedReader(fluxo, 1 << 20)),
                                        args.quantidade, args.rating_min, args.rating_max,
                                        args.popularidade_min, args.jogadas_min,
                                        args.semente, progresso_factory(fluxo), args.max_linhas)

    salvar(puzzles, args.saida)
    print(
        f"Pronto: {len(puzzles):,} puzzles (de {validos:,} válidos) salvos em {args.saida} "
        f"em {time.time() - inicio:.0f}s",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
