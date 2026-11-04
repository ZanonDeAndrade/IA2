# Dados

> **A base completa de puzzles NÃO vai para o Git.**
> Arquivos `*.csv`, `*.zst`, `*.db` e `*.sqlite` dentro desta pasta estão no
> `.gitignore` da raiz. O script em `scripts/` baixa e prepara tudo.

## Base de puzzles da Lichess (CC0)

- Fonte: <https://database.lichess.org/#puzzles>
- Arquivo: `lichess_db_puzzle.csv.zst` (cerca de 6 milhões de puzzles; gigabytes
  descompactado)
- Colunas: `PuzzleId, FEN, Moves, Rating, RatingDeviation, Popularity, NbPlays,
  Themes, GameUrl, OpeningTags`
- Licença: CC0 (domínio público)

O script `scripts/download_puzzles.py` baixa o arquivo, descompacta, mantém só
um **recorte** (por exemplo, 50 mil puzzles com rating entre 600 e 2200) e
salva em SQLite (`data/puzzles.sqlite`), que é o que a ferramenta
`buscar_puzzles` consulta.

```bash
# a partir de trabalho-2/
python data/scripts/download_puzzles.py --rating-min 600 --rating-max 2200 --quantidade 50000
```

## Temas

A coluna `Themes` usa nomes em inglês (`fork`, `pin`, `skewer`,
`hangingPiece`, `discoveredAttack`, ...). O dicionário inglês → português fica
no código e é compartilhado pelo agente, pela interface e pelas fichas em
`knowledge_base/`.

## Partidas do Chess.com

As partidas vêm da API pública (sem chave, mas com `User-Agent` obrigatório,
ver `.env.example`) e são guardadas em cache no SQLite do backend. Nada delas
precisa ser versionado.
