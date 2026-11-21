FROM lance_base
RUN apt-get update && apt-get install -y --no-install-recommends stockfish \
    && rm -rf /var/lib/apt/lists/*
ENV STOCKFISH_PATH=/usr/games/stockfish
ENTRYPOINT ["/bin/sh", "/app/mcp_server/entrypoint.sh"]
