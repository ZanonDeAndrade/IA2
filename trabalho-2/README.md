# Lance a Lance – treinador de xadrez com IA

> Trabalho 2 de Inteligência Artificial II (opção 3: integração com IA em
> contexto avançado – agente, MCP e RAG).

Um agente de IA explica, em português, os erros do jogador em suas partidas,
ancorado no **Stockfish**: o LLM nunca calcula lances, só interpreta o que as
ferramentas devolvem. As partidas vêm da API pública do **Chess.com**, os
puzzles da base aberta da **Lichess** (CC0) e as ferramentas são expostas via
**MCP** (FastMCP).

📄 Documentação completa do projeto (requisitos, arquitetura, avaliação,
divisão do trabalho e cronograma):
[`docs/lance-a-lance-documentacao-do-projeto.pdf`](docs/lance-a-lance-documentacao-do-projeto.pdf)

## Problema

(em construção)

## Solução e abordagem

(em construção)

## Arquitetura

(em construção)

Três camadas: interface web (React), backend com o agente (FastAPI + LangGraph)
e servidor MCP que expõe o motor, as regras do jogo e as bases de dados como
ferramentas.

```
trabalho-2/
├── mcp_server/      # FastMCP: ferramentas determinísticas (motor, tabuleiro, Chess.com, puzzles, RAG)
├── agent/           # LangGraph: fluxo de explicação, chat, classificador e validador
├── backend/         # FastAPI + cache SQLite
├── frontend/        # React + Vite + react-chessboard (mocks em src/mocks/)
├── knowledge_base/  # fichas de conceitos (Markdown) indexadas no ChromaDB
├── data/            # scripts da base de puzzles (a base NÃO vai para o Git)
├── evaluation/      # avaliação A × B × C e resultados
└── docs/            # documentação e prints
```

## Ferramentas MCP

Sete ferramentas determinísticas expostas pelo servidor FastMCP
([`mcp_server/server.py`](mcp_server/server.py)). São a única fonte de fatos
sobre o tabuleiro que o agente pode usar. Cada chamada fica registrada em
`logs/mcp_tools.jsonl` (RNF06).

| Ferramenta | Entrada | Saída | Fonte |
|---|---|---|---|
| `analisar_posicao` | `fen`, `profundidade=18`, `multipv=3` | avaliação, melhores lances em SAN, linha principal | Stockfish |
| `analisar_partida` | `pgn`, `cor_do_jogador` | lista por lance com avaliação, queda, classe e melhor lance | Stockfish |
| `validar_lances` | `fen`, `lances` | legalidade e SAN normalizado de cada lance (aceita SAN em inglês e português, e UCI) | python-chess |
| `descrever_posicao` | `fen` | material, peças atacadas/indefesas, cravadas, espetos, xeques, garfos, mate em 1, rei exposto | python-chess |
| `buscar_partidas` | `usuario`, `max=10`, `ritmo=None` | partidas com PGN, cores, resultado e abertura | API do Chess.com |
| `buscar_puzzles` | `temas`, `rating_min`, `rating_max`, `quantidade=5` | puzzles com FEN, solução, rating e link | base Lichess (SQLite) |
| `buscar_conceitos` | `pergunta`, `k=4` | trechos das fichas com título e tema | RAG · ChromaDB |

Formato detalhado de cada ferramenta e de cada endpoint da API:
[`docs/API.md`](docs/API.md).

## Como executar

Stack: Python 3.11, python-chess, Stockfish, FastMCP, LangGraph +
langchain-mcp-adapters, ChromaDB, FastAPI, SQLite, React + Vite +
react-chessboard, Docker Compose.

### Pré-requisitos

- **Docker:** Docker Desktop com Compose v2.24 ou mais novo. O Stockfish já vem
  na imagem.
- **Local:** Python 3.11+, Stockfish no `PATH` (`brew install stockfish` /
  `sudo apt install stockfish`) e Node 20+ para o frontend.

### 1. Configurar

```bash
cd trabalho-2
cp .env.example .env
```

No `.env`, preencha `CHESSCOM_USER_AGENT` com o nome do app e um contato (sem
isso a API do Chess.com responde 403) e `LLM_PROVIDER` / `LLM_API_KEY` para o
agente.

### 2. Baixar a base de puzzles (uma vez)

O script lê a base aberta da Lichess (CC0, cerca de 300 MB compactada) em
streaming e salva um recorte de 50 mil puzzles com rating entre 600 e 2200 em
`data/puzzles.sqlite`. Nada disso vai para o Git.

```bash
python data/scripts/download_puzzles.py --rating-min 600 --rating-max 2200 --quantidade 50000
# ou, com Docker:
docker compose run --rm puzzles
```

Se o download estiver lento, `--max-linhas 300000` lê só o começo do arquivo.
Como a base vem ordenada pelo id do puzzle, que é aleatório, o começo já é uma
amostra representativa. Para usar um `.zst` já baixado:
`--arquivo caminho/lichess_db_puzzle.csv.zst`.

### 3a. Subir com Docker

```bash
docker compose up --build
```

- API: http://localhost:8000 (Swagger em http://localhost:8000/docs)
- Servidor MCP: http://localhost:8001/mcp

### 3b. Subir localmente

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

Sem `MCP_URL`, o backend carrega o servidor MCP no mesmo processo. Para rodar o
MCP separado, como no Docker:

```bash
MCP_TRANSPORT=http python -m mcp_server.server              # terminal 1
MCP_URL=http://localhost:8001/mcp uvicorn backend.main:app  # terminal 2
```

Inspetor do FastMCP, para testar as ferramentas uma a uma:

```bash
fastmcp dev mcp_server/server.py
```

### 4. Testes

```bash
pytest
```

Os testes cobrem as ferramentas, a classificação, a notação, o cliente do
Chess.com (com a API simulada), os puzzles e a API de ponta a ponta. Os que
dependem do Stockfish são pulados se ele não estiver instalado.

### Exemplo pela API

```bash
curl -X POST localhost:8000/api/partidas/importar -H 'content-type: application/json' \
     -d '{"usuario": "erik", "max": 5}'
curl -X POST localhost:8000/api/partidas/<id>/analisar   # devolve tarefa_id
curl localhost:8000/api/tarefas/<tarefa_id>              # progresso
curl localhost:8000/api/partidas/<id>                    # lances, classes e explicações
curl localhost:8000/api/relatorio/erik                   # temas fracos e puzzles
```

`python -m backend.gerar_exemplos --usuario erik` repete esse fluxo e grava as
respostas em [`docs/api/exemplos/`](docs/api/exemplos/). Numa partida real de 41
lances, a análise com explicações levou cerca de 15 s (RNF02 pede até 60 s).

## Como reproduzir a avaliação

(em construção)

```bash
python evaluation/run_eval.py
```

## Resultados

(em construção)

## Prints

(em construção)

## Limitações e próximos passos

(em construção)

## Equipe

(em construção)

## Licenças e créditos

(em construção)

- Partidas: API pública do [Chess.com](https://www.chess.com/news/view/published-data-api) (dados públicos, somente leitura).
- Puzzles: [base aberta da Lichess](https://database.lichess.org/#puzzles) (CC0).
- Motor: [Stockfish](https://stockfishchess.org/) (GPL, usado como programa externo).
- Fichas de conceitos: escritas pelo grupo.
