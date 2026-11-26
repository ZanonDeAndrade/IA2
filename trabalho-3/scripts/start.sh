#!/usr/bin/env bash
# Sobe Ollama (se preciso), backend FastAPI (com o servidor MCP via stdio) e frontend Vite.
# Uso: scripts/start.sh            (a partir de trabalho-3/)   Ctrl+C encerra backend e frontend.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OLLAMA_BIN="${OLLAMA_BIN:-$(command -v ollama || echo "$HOME/.local/ollama/bin/ollama")}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT=5173  # fixo em frontend/vite.config.ts e no CORS padrão do backend

export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:1.7b}"            # cabe na RAM/CPU desta máquina (qwen3:4b é o padrão da doc)
export RAG_RETRIEVER="${RAG_RETRIEVER:-rag.wikibooks:retrieve}"  # índice Chroma do corpus Wikilivros
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"                  # modelo de embeddings já baixado pela ingestão
export INFERENCE_TIMEOUT="${INFERENCE_TIMEOUT:-300}"

port_pid() { ss -ltnpH "sport = :$1" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2; }

for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if ss -ltnH "sport = :$port" | grep -q .; then
    pid="$(port_pid "$port")"
    echo "ERRO: a porta $port já está em uso${pid:+ (PID $pid: $(ps -o args= -p "$pid" | cut -c1-80))}." >&2
    echo "Encerre o processo antes (ex.: kill ${pid:-<PID>}) ou feche a outra instância da aplicação." >&2
    exit 1
  fi
done

if [ ! -f "$ROOT/data/normalized/recipes.json" ] || [ ! -d "$ROOT/data/chroma_wikibooks" ]; then
  echo "ERRO: corpus não indexado. Rode: mcp-server/.venv/bin/python -m rag.wikibooks build" >&2
  exit 1
fi

if ! curl -s -o /dev/null http://localhost:11434/api/version; then
  echo "Iniciando Ollama ($OLLAMA_BIN)..."
  nohup "$OLLAMA_BIN" serve > "$ROOT/ollama.log" 2>&1 &
  for _ in $(seq 1 30); do curl -s -o /dev/null http://localhost:11434/api/version && break; sleep 1; done
fi
"$OLLAMA_BIN" list | grep -q "^${OLLAMA_MODEL}" || "$OLLAMA_BIN" pull "$OLLAMA_MODEL"

cd "$ROOT/backend"
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" &
BACKEND=$!
trap 'kill $BACKEND 2>/dev/null || true' EXIT INT TERM

echo "Aguardando o backend (inicia o servidor MCP)..."
for _ in $(seq 1 60); do
  curl -s -o /dev/null "http://127.0.0.1:$BACKEND_PORT/health" && break
  kill -0 "$BACKEND" 2>/dev/null || { echo "ERRO: o backend encerrou ao iniciar (veja as mensagens acima)." >&2; exit 1; }
  sleep 1
done
echo "Estado: $(curl -s "http://127.0.0.1:$BACKEND_PORT/ready")"

echo "Frontend em http://localhost:$FRONTEND_PORT"
cd "$ROOT/frontend"
npm run dev
