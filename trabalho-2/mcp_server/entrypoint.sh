#!/bin/sh
set -eu
if [ ! -s "$PUZZLES_DB" ]; then
    python -m data.scripts.download_puzzles --recorte-versionado --saida "$PUZZLES_DB"
fi
python -m knowledge_base.index
exec python -m mcp_server.server --http --host 0.0.0.0 "$@"
