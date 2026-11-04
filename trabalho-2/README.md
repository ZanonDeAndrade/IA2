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

(em construção)

| Ferramenta | Entrada | Saída |
|---|---|---|
| `analisar_posicao` | `fen`, `profundidade=18`, `multipv=3` | avaliação, melhores lances, linha principal |
| `analisar_partida` | `pgn`, `cor_do_jogador` | lista por lance com avaliação, queda, classe e melhor lance |
| `validar_lances` | `fen`, `lances` | legalidade e SAN normalizado de cada lance |
| `descrever_posicao` | `fen` | material, peças atacadas/indefesas, cravadas, xeques, rei exposto |
| `buscar_partidas` | `usuario`, `max=10`, `ritmo=None` | partidas com PGN, cores, resultado e abertura |
| `buscar_puzzles` | `temas`, `rating_min`, `rating_max`, `quantidade=5` | puzzles com FEN, solução, rating e link |
| `buscar_conceitos` | `pergunta`, `k=4` | trechos das fichas com título e tema |

## Como executar

(em construção)

Stack: Python 3.11, python-chess, FastMCP, LangGraph + langchain-mcp-adapters,
ChromaDB, FastAPI, SQLite, React + Vite + react-chessboard, Docker Compose.

```bash
cp .env.example .env   # preencha as variáveis
docker compose up
```

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
