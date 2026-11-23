"""Mede o modo Jogar contra IA pela API HTTP real.

Separa as três etapas pedidas pelo treinador em tempo real:

- adversário: ``tempos.adversario_ms`` do lance do Stockfish;
- avaliação: ``tempos.avaliacao_ms`` do lance do jogador;
- explicação: ``duracao_ms`` da tarefa do treinador, gerada sem cache.

Os lances do jogador são sorteados entre os legais com semente reproduzível.
O cache de posições do Stockfish continua ativo. Uso, com a API em execução:

    python -m data.scripts.benchmark_treinador http://127.0.0.1:8000 --partidas 3 --lances 8
"""

import argparse
import json
from random import Random
from statistics import mean, median
import time

import httpx


def resumo(valores: list[float]) -> dict:
    return {"amostras": len(valores), "media_ms": round(mean(valores), 1) if valores else None,
            "mediana_ms": round(median(valores), 1) if valores else None, "maximo_ms": max(valores) if valores else None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("api")
    parser.add_argument("--partidas", type=int, default=3)
    parser.add_argument("--lances", type=int, default=8)
    parser.add_argument("--semente", type=int, default=7)
    parser.add_argument("--saida")
    args = parser.parse_args()
    sorteio = Random(args.semente)
    cliente = httpx.Client(base_url=args.api.rstrip("/"), timeout=200)
    niveis = ["iniciante", "intermediario", "avancado"]
    turnos, adversario, avaliacao, jogos = [], {n: [] for n in niveis}, [], []
    for numero in range(args.partidas):
        nivel = niveis[numero % len(niveis)]
        jogo = cliente.post("/api/jogo/iniciar", json={"cor_do_jogador": "white", "dificuldade": nivel,
                                                       "modo_assistencia": "treinador"}).raise_for_status().json()
        for _ in range(args.lances):
            if jogo["status"] != "em_andamento":
                break
            lance = sorteio.choice(sorted(jogo["lances_legais"]))
            inicio = time.perf_counter()
            jogo = cliente.post(f"/api/jogo/{jogo['id']}/mover",
                                json={"lance": lance, "versao": jogo["versao"]}).raise_for_status().json()
            turnos.append((time.perf_counter() - inicio) * 1000)
            meu = [l for l in jogo["lances"] if l["autor"] == "jogador"][-1]
            avaliacao.append(meu["tempos"]["avaliacao_ms"])
            if jogo["lances"][-1]["autor"] == "ia":
                adversario[nivel].append(jogo["lances"][-1]["tempos"]["adversario_ms"])
        jogos.append(jogo["id"])
    explicacoes, fontes = [], []
    prazo = time.time() + 900
    for id_ in jogos:
        while time.time() < prazo:
            painel = cliente.get(f"/api/jogo/{id_}/treinador").json()
            if all(e["status"] not in {"pendente", "em_andamento"} for e in painel["explicacoes"]):
                break
            time.sleep(2)
        for item in painel["explicacoes"]:
            resultado = item.get("resultado") or {}
            if item["status"] == "concluida" and not resultado.get("cache"):
                explicacoes.append(item["duracao_ms"])
                fontes.append(resultado.get("fonte"))
    relatorio = {
        "turno_completo_cliente": resumo(turnos),
        "adversario_por_nivel": {nivel: resumo(valores) for nivel, valores in adversario.items()},
        "avaliacao": resumo(avaliacao),
        "explicacao": resumo(explicacoes) | {"fontes": {f: fontes.count(f) for f in set(fontes)}},
        "partidas": jogos,
    }
    texto = json.dumps(relatorio, ensure_ascii=False, indent=2)
    print(texto)
    if args.saida:
        with open(args.saida, "w", encoding="utf-8") as arquivo:
            arquivo.write(texto + "\n")


if __name__ == "__main__":
    main()
