"""Mede uma análise de até 80 meios-lances reais pela API HTTP."""

import argparse
import json
from pathlib import Path
from time import perf_counter, sleep

import chess.pgn
import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pgn", type=Path)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--meios-lances", type=int, default=80)
    parser.add_argument("--prazo", type=float, default=180)
    args = parser.parse_args()

    with args.pgn.open(encoding="utf-8-sig") as arquivo:
        original = chess.pgn.read_game(arquivo)
    if not original or original.errors or args.meios_lances < 1 or args.prazo <= 0:
        parser.error("PGN ou limites inválidos.")
    lances = list(original.mainline_moves())
    if len(lances) < args.meios_lances:
        parser.error("Use uma partida com pelo menos a quantidade de meios-lances solicitada.")

    jogo = chess.pgn.Game.from_board(original.board())
    jogo.headers.update(original.headers)
    if len(lances) != args.meios_lances:
        jogo.headers["Result"] = "*"
    no = jogo
    for lance in lances[:args.meios_lances]:
        no = no.add_variation(lance)
    pgn = jogo.accept(chess.pgn.StringExporter(headers=True, variations=False, comments=False))

    with httpx.Client(base_url=args.api, timeout=10) as cliente:
        importacao = cliente.post("/api/partidas/importar", json={"pgn": pgn, "cor_do_jogador": "white"})
        importacao.raise_for_status()
        partida = importacao.json()["partidas"][0]
        rota = f"/api/partidas/{partida['id']}/analisar"
        inicio = perf_counter()
        resposta = cliente.post(rota)
        resposta.raise_for_status()
        tarefa = resposta.json()["tarefa_id"]
        while perf_counter() - inicio < args.prazo:
            resposta = cliente.get(f"/api/tarefas/{tarefa}")
            resposta.raise_for_status()
            progresso = resposta.json()
            if progresso["status"] == "erro":
                raise SystemExit(progresso["erro"])
            if progresso["status"] == "concluida":
                break
            sleep(0.1)
        else:
            raise SystemExit("Prazo do benchmark excedido.")
        tempo = perf_counter() - inicio
        inicio_cache = perf_counter()
        repeticao = cliente.post(rota)
        repeticao.raise_for_status()
        if repeticao.json()["tarefa_id"] != tarefa:
            raise SystemExit("A repetição não reutilizou a tarefa concluída.")
        print(json.dumps({
            "origem_pgn": str(args.pgn), "partida_id": partida["id"], "meios_lances": args.meios_lances,
            "segundos": round(tempo, 3), "segundos_cache": round(perf_counter() - inicio_cache, 3),
            "cache_previo_partida": partida["status_analise"] == "concluida",
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
