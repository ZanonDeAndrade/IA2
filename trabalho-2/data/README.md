# Dados locais

O Git guarda as fichas e as posições rastreadas da avaliação. Bancos SQLite,
o índice ChromaDB e o arquivo de puzzles compactado são gerados localmente.

## Puzzles públicos da Lichess

Prepare um recorte inicial a partir das linhas públicas preservadas para a
avaliação. A base de recomendação e o dataset A/B/C têm propósitos diferentes.

```bash
python -m data.scripts.download_puzzles --recorte-versionado
```

Baixe e prepare um recorte maior quando precisar ampliar a cobertura:

```bash
python -m data.scripts.download_puzzles --rating-min 600 --rating-max 2200 --quantidade 50000
```

Use `--arquivo /caminho/lichess_db_puzzle.csv.zst` para reaproveitar um download
e `--prefixo 100000` para limitar o número de registros examinados. O processo
lê o CSV em streaming, reserva espaço para os temas principais, completa a
amostra com outros registros e valida a linha UCI. O SQLite só substitui o
arquivo de destino depois de gravar o recorte válido.

O FEN público antecede a primeira jogada de `Moves`. Para resolver o puzzle,
a API aplica essa jogada, informa a posição resultante em `fen` e entrega os
meios-lances restantes em `solucao`. O FEN público e a jogada preparatória
permanecem em `fen_origem` e `lance_preparatorio`. [Formato oficial](https://database.lichess.org/#puzzles)

O arquivo padrão é `data/puzzles.sqlite`. Use `--saida` na preparação e
`PUZZLES_DB` no MCP para outro caminho.

## Partidas e cache

Configure `CHESSCOM_USER_AGENT` com nome e contato do app. O MCP busca os
arquivos mensais mais recentes primeiro, serializa requisições e usa um cache
local. A rota de PGN permite importar uma partida mesmo quando a fonte externa
estiver indisponível. O SQLite padrão de importação, tarefas e análise é
`data/lance.sqlite`, configurável por `SQLITE_PATH`.
