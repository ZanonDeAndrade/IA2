#!/usr/bin/env bash
# Sobe Ollama (se preciso), backend FastAPI (com o servidor MCP via stdio) e frontend Vite.
# Uso: scripts/start.sh            (a partir de trabalho-3/)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OLLAMA_BIN="${OLLAMA_BIN:-$(command -v ollama || echo "$HOME/.local/ollama/bin/ollama")}"

export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:1.7b}"            # cabe na RAM/CPU desta máquina (qwen3:4b é o padrão da doc)
export RAG_RETRIEVER="${RAG_RETRIEVER:-rag.wikibooks:retrieve}"  # índice Chroma do corpus Wikilivros
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"                  # modelo de embeddings já baixado pela ingestão
export INFERENCE_TIMEOUT="${INFERENCE_TIMEOUT:-300}"

if ! curl -s -o /dev/null http://localhost:11434/api/version; then
  echo "Iniciando Ollama ($OLLAMA_BIN)..."
  nohup "$OLLAMA_BIN" serve > "$ROOT/ollama.log" 2>&1 &
  sleep 3
fi
"$OLLAMA_BIN" list | grep -q "^${OLLAMA_MODEL}" || "$OLLAMA_BIN" pull "$OLLAMA_MODEL"

cd "$ROOT/backend"
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 &
BACKEND=$!
trap 'kill $BACKEND 2>/dev/null || true' EXIT

cd "$ROOT/frontend"
npm run dev
