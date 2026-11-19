# Servidor MCP (FastMCP em HTTP na porta 8001). Contexto do build: trabalho-2/
FROM python:3.11-slim

# Stockfish do Debian, acionado pelo python-chess via UCI.
RUN apt-get update \
    && apt-get install -y --no-install-recommends stockfish \
    && rm -rf /var/lib/apt/lists/*
ENV STOCKFISH_PATH=/usr/games/stockfish \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_TRANSPORT=http \
    MCP_PORT=8001

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_server/ mcp_server/
COPY data/scripts/ data/scripts/
COPY knowledge_base/ knowledge_base/

EXPOSE 8001
CMD ["python", "-m", "mcp_server.server"]
