"""Gera respostas reais da API em docs/api/exemplos/ (para comparar com os mocks do front).

Importa partidas de um usuário do Chess.com, analisa a mais longa (até 60
lances) e salva um JSON por endpoint. Também mede o tempo da análise (RNF02).

Uso (a partir de ``trabalho-2/``):
    python -m backend.gerar_exemplos --usuario erik
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "docs" / "api" / "exemplos"


def salvar(nome: str, rota: str, resposta) -> dict:
    DESTINO.mkdir(parents=True, exist_ok=True)
    corpo = resposta.json()
    (DESTINO / f"{nome}.json").write_text(json.dumps(corpo, ensure_ascii=False, indent=2) + "\n")
    print(f"  {nome}.json  ({rota} -> {resposta.status_code})", file=sys.stderr)
    return corpo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--usuario", default="erik")
    ap.add_argument("--max", type=int, default=10)
    args = ap.parse_args()

    # Banco temporário, para os exemplos não dependerem do cache local.
    os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "exemplos.sqlite")
    os.environ.setdefault("MCP_URL", "")

    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as c:
        partidas = salvar("partidas", "POST /api/partidas/importar",
                          c.post("/api/partidas/importar", json={"usuario": args.usuario, "max": args.max}))["partidas"]
        curtas = [p for p in partidas if (p["total_lances"] or 0) <= 60]
        alvo = max(curtas, key=lambda p: p["total_lances"] or 0)

        inicio = time.perf_counter()
        tarefa = c.post(f"/api/partidas/{alvo['id']}/analisar").json()
        duracao = time.perf_counter() - inicio
        salvar("tarefa", f"GET /api/tarefas/{tarefa['tarefa_id']}", c.get(f"/api/tarefas/{tarefa['tarefa_id']}"))
        partida = salvar("partida", f"GET /api/partidas/{alvo['id']}", c.get(f"/api/partidas/{alvo['id']}"))
        print(f"  RNF02: {alvo['total_lances']} lances analisados e explicados em {duracao:.1f}s", file=sys.stderr)

        erro = next((l for l in partida["lances"] if l["classe"] in ("erro_grave", "erro")), partida["lances"][0])
        salvar("explicacao", "POST /api/explicar",
               c.post("/api/explicar", json={"fen": erro["fen_antes"], "lance_jogado": erro["san"]}))

        for p in curtas[:5]:  # mais partidas para o relatório
            c.post(f"/api/partidas/{p['id']}/analisar")
        salvar("relatorio", f"GET /api/relatorio/{args.usuario}", c.get(f"/api/relatorio/{args.usuario}"))
        salvar("chat_sem_agente", "POST /api/chat",
               c.post("/api/chat", json={"fen": erro["fen_antes"], "pergunta": "Por que esse lance é ruim?"}))
        salvar("erro_usuario_inexistente", "POST /api/partidas/importar",
               c.post("/api/partidas/importar", json={"usuario": "usuario-que-nao-existe-xyz123"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
