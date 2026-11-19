# API FastAPI + agente. Contexto do build: trabalho-2/
# Inclui o Stockfish para o modo sem MCP_URL (servidor MCP no mesmo processo).
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends stockfish \
    && rm -rf /var/lib/apt/lists/*
ENV STOCKFISH_PATH=/usr/games/stockfish \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_server/ mcp_server/
COPY agent/ agent/
COPY backend/ backend/
COPY knowledge_base/ knowledge_base/

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
